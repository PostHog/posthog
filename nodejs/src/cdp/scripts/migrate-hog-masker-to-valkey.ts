import IORedis, { Redis } from 'ioredis'
import { parseArgs } from 'node:util'

import { HOG_MASKER_KEY_PATTERN } from '../services/monitoring/hog-masker.constants'

const KEY_PATTERN = HOG_MASKER_KEY_PATTERN

type Phase = 'copy' | 'finalize' | 'verify'
type MigrationOptions = {
    phase: Phase
    execute: boolean
    writersPaused: boolean
    scanCount: number
    ttlToleranceMs: number
}
type MigrationSummary = {
    sourceKeys: number
    copiedKeys: number
    skippedExpiredKeys: number
    deletedExtraKeys: number
    mismatchedValues: number
    mismatchedExpiries: number
    missingTargetKeys: number
    extraTargetKeys: number
}

function emptySummary(): MigrationSummary {
    return {
        sourceKeys: 0,
        copiedKeys: 0,
        skippedExpiredKeys: 0,
        deletedExtraKeys: 0,
        mismatchedValues: 0,
        mismatchedExpiries: 0,
        missingTargetKeys: 0,
        extraTargetKeys: 0,
    }
}

function connectionFromEnv(prefix: 'CDP_REDIS' | 'CDP_VALKEY'): Redis {
    const host = process.env[`${prefix}_HOST`]
    if (!host) {
        throw new Error(`${prefix}_HOST is required`)
    }
    const port = Number(process.env[`${prefix}_PORT`] || '6379')
    const password = process.env[`${prefix}_PASSWORD`] || undefined
    const tls = process.env[`${prefix}_TLS`] === 'true' ? {} : undefined
    return new IORedis({ host, port, password, tls, lazyConnect: true, maxRetriesPerRequest: 3 })
}

async function* scanBatches(redis: Redis, count: number): AsyncGenerator<string[]> {
    let cursor = '0'
    do {
        const [nextCursor, keys] = await redis.scan(cursor, 'MATCH', KEY_PATTERN, 'COUNT', count)
        cursor = nextCursor
        if (keys.length > 0) {
            yield keys
        }
    } while (cursor !== '0')
}

function sourceTimeMs([seconds, microseconds]: [string, string]): number {
    return Number(seconds) * 1000 + Math.floor(Number(microseconds) / 1000)
}

async function copySourceKeys(
    source: Redis,
    target: Redis,
    options: MigrationOptions,
    summary: MigrationSummary
): Promise<void> {
    for await (const keys of scanBatches(source, options.scanCount)) {
        summary.sourceKeys += keys.length
        if (!options.execute) {
            continue
        }

        const sourcePipeline = source.pipeline()
        for (const key of keys) {
            sourcePipeline.get(key)
            sourcePipeline.pttl(key)
        }
        const [time, rows] = await Promise.all([source.time(), sourcePipeline.exec()])
        if (!rows) {
            throw new Error('Source Redis pipeline returned no results')
        }

        const nowMs = sourceTimeMs(time)
        const targetPipeline = target.pipeline()
        keys.forEach((key, index) => {
            const value = rows[index * 2]?.[1] as string | null
            const ttlMs = Number(rows[index * 2 + 1]?.[1])
            if (value === null || ttlMs <= 0) {
                summary.skippedExpiredKeys++
                return
            }
            targetPipeline.set(key, value, 'PXAT', nowMs + ttlMs)
            summary.copiedKeys++
        })
        await targetPipeline.exec()
    }
}

async function deleteTargetExtras(
    source: Redis,
    target: Redis,
    options: MigrationOptions,
    summary: MigrationSummary
): Promise<void> {
    for await (const keys of scanBatches(target, options.scanCount)) {
        const existsPipeline = source.pipeline()
        keys.forEach((key) => existsPipeline.exists(key))
        const rows = await existsPipeline.exec()
        if (!rows) {
            throw new Error('Source Redis existence pipeline returned no results')
        }
        const extras = keys.filter((_, index) => Number(rows[index]?.[1]) === 0)
        summary.extraTargetKeys += extras.length
        if (options.execute && extras.length > 0) {
            summary.deletedExtraKeys += await target.del(...extras)
        }
    }
}

async function verifyKeys(
    source: Redis,
    target: Redis,
    options: MigrationOptions,
    summary: MigrationSummary
): Promise<void> {
    for await (const keys of scanBatches(source, options.scanCount)) {
        const sourcePipeline = source.pipeline()
        const targetPipeline = target.pipeline()
        for (const key of keys) {
            sourcePipeline.get(key)
            sourcePipeline.pttl(key)
            targetPipeline.get(key)
            targetPipeline.pttl(key)
        }
        const [sourceRows, targetRows] = await Promise.all([sourcePipeline.exec(), targetPipeline.exec()])
        if (!sourceRows || !targetRows) {
            throw new Error('Verification pipeline returned no results')
        }
        keys.forEach((_, index) => {
            const sourceValue = sourceRows[index * 2]?.[1] as string | null
            const sourceTtl = Number(sourceRows[index * 2 + 1]?.[1])
            const targetValue = targetRows[index * 2]?.[1] as string | null
            const targetTtl = Number(targetRows[index * 2 + 1]?.[1])
            if (sourceValue === null || sourceTtl <= 0) {
                return
            }
            if (targetValue === null) {
                summary.missingTargetKeys++
                return
            }
            if (sourceValue !== targetValue) {
                summary.mismatchedValues++
            }
            if (Math.abs(sourceTtl - targetTtl) > options.ttlToleranceMs) {
                summary.mismatchedExpiries++
            }
        })
    }
    await deleteTargetExtras(source, target, { ...options, execute: false }, summary)
}

function parseOptions(): MigrationOptions {
    const { values } = parseArgs({
        options: {
            phase: { type: 'string', default: 'copy' },
            execute: { type: 'boolean', default: false },
            'writers-paused': { type: 'boolean', default: false },
            'scan-count': { type: 'string', default: '500' },
            'ttl-tolerance-ms': { type: 'string', default: '2000' },
            help: { type: 'boolean', default: false },
        },
    })
    if (values.help) {
        console.log(`Usage: migrate-hog-masker-to-valkey [options]

  --phase copy       Copy source keys while Redis remains authoritative (default)
  --phase finalize   Exact copy and remove target-only keys; requires paused writers
  --phase verify     Compare values and expiries without writing
  --execute          Apply changes; omitted means dry-run
  --writers-paused   Confirm every HogMasker writer is paused
  --scan-count N     Redis SCAN batch size (default: 500)
  --ttl-tolerance-ms N  Allowed expiry difference during verify (default: 2000)

Connections come from CDP_REDIS_* (source) and CDP_VALKEY_* (target).`)
        process.exit(0)
    }
    if (!['copy', 'finalize', 'verify'].includes(values.phase)) {
        throw new Error(`Invalid --phase: ${values.phase}`)
    }
    const phase = values.phase as Phase
    if (phase === 'finalize' && (!values.execute || !values['writers-paused'])) {
        throw new Error('--phase finalize requires both --execute and --writers-paused')
    }
    const scanCount = Number(values['scan-count'])
    const ttlToleranceMs = Number(values['ttl-tolerance-ms'])
    if (!Number.isInteger(scanCount) || scanCount < 1 || !Number.isFinite(ttlToleranceMs) || ttlToleranceMs < 0) {
        throw new Error('Scan count must be a positive integer and TTL tolerance must be non-negative')
    }
    return { phase, execute: values.execute, writersPaused: values['writers-paused'], scanCount, ttlToleranceMs }
}

async function main(): Promise<void> {
    const options = parseOptions()
    const sourceHost = process.env.CDP_REDIS_HOST
    const targetHost = process.env.CDP_VALKEY_HOST
    if (
        sourceHost === targetHost &&
        (process.env.CDP_REDIS_PORT || '6379') === (process.env.CDP_VALKEY_PORT || '6379')
    ) {
        throw new Error('Source Redis and target Valkey must be different endpoints')
    }
    const source = connectionFromEnv('CDP_REDIS')
    const target = connectionFromEnv('CDP_VALKEY')
    const summary = emptySummary()
    try {
        await Promise.all([source.connect(), target.connect()])
        await Promise.all([source.ping(), target.ping()])
        if (options.phase === 'copy' || options.phase === 'finalize') {
            await copySourceKeys(source, target, options, summary)
        }
        if (options.phase === 'finalize') {
            await deleteTargetExtras(source, target, options, summary)
        }
        if (options.phase === 'verify' || options.phase === 'finalize') {
            await verifyKeys(source, target, options, summary)
        }
        console.log(
            JSON.stringify({ phase: options.phase, dryRun: !options.execute, pattern: KEY_PATTERN, ...summary })
        )
        const undeletedExtraKeys = summary.extraTargetKeys - summary.deletedExtraKeys
        if (
            summary.mismatchedValues ||
            summary.mismatchedExpiries ||
            summary.missingTargetKeys ||
            (options.phase !== 'copy' && undeletedExtraKeys > 0)
        ) {
            process.exitCode = 2
        }
    } finally {
        await Promise.allSettled([source.quit(), target.quit()])
    }
}

void main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error))
    process.exitCode = 1
})
