import { Redis } from 'ioredis'

import { MASK_KEY_PREFIX } from '../services/monitoring/hog-masker.keys'

export const DEFAULT_KEY_PATTERN = `${MASK_KEY_PREFIX}*`

export type MigrationPhase = 'stats' | 'copy' | 'check'

export type MaskerMigrationOptions = {
    phase: MigrationPhase
    /** Only read by the copy phase; stats and check never write. */
    execute: boolean
    keyPattern: string
    scanCount: number
    /** Stop after this many scanned keys, so a run can be sized to fit a pod session. */
    limit: number | null
    sleepMsBetweenBatches: number
    ttlToleranceMs: number
    sampleKeysPerBucket: number
}

export type TtlBucket = 'under1h' | 'under1d' | 'under7d' | 'under30d' | 'under1y' | 'over1y' | 'noExpiry'

const TTL_BUCKET_UPPER_BOUNDS_MS: [Exclude<TtlBucket, 'noExpiry' | 'over1y'>, number][] = [
    ['under1h', 60 * 60 * 1000],
    ['under1d', 24 * 60 * 60 * 1000],
    ['under7d', 7 * 24 * 60 * 60 * 1000],
    ['under30d', 30 * 24 * 60 * 60 * 1000],
    ['under1y', 365 * 24 * 60 * 60 * 1000],
]

export type MigrationSamples = {
    missingFromTarget: string[]
    valueDrift: string[]
    expiryDrift: string[]
    targetOnly: string[]
}

export type MigrationSummary = {
    phase: MigrationPhase
    dryRun: boolean
    scannedSourceKeys: number
    scannedTargetKeys: number
    /** True when --limit cut the scan short, so the counts are a sample rather than a total. */
    limitReached: boolean
    presentInTarget: number
    missingFromTarget: number
    copiedKeys: number
    /** Keys SCAN returned that had already expired by the time we read them. */
    skippedExpiredKeys: number
    valueDrift: number
    targetBehindSource: number
    targetAheadOfSource: number
    expiryDrift: number
    targetOnlyKeys: number
    sourceTtlBuckets: Record<TtlBucket, number>
    samples: MigrationSamples
}

export function emptyMigrationSummary(phase: MigrationPhase, dryRun: boolean): MigrationSummary {
    return {
        phase,
        dryRun,
        scannedSourceKeys: 0,
        scannedTargetKeys: 0,
        limitReached: false,
        presentInTarget: 0,
        missingFromTarget: 0,
        copiedKeys: 0,
        skippedExpiredKeys: 0,
        valueDrift: 0,
        targetBehindSource: 0,
        targetAheadOfSource: 0,
        expiryDrift: 0,
        targetOnlyKeys: 0,
        sourceTtlBuckets: {
            under1h: 0,
            under1d: 0,
            under7d: 0,
            under30d: 0,
            under1y: 0,
            over1y: 0,
            noExpiry: 0,
        },
        samples: { missingFromTarget: [], valueDrift: [], expiryDrift: [], targetOnly: [] },
    }
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}

function recordSample(samples: string[], key: string, sampleKeysPerBucket: number): void {
    if (samples.length < sampleKeysPerBucket) {
        samples.push(key)
    }
}

function recordTtlBucket(buckets: Record<TtlBucket, number>, ttlMs: number): void {
    if (ttlMs < 0) {
        buckets.noExpiry++
        return
    }
    const bucket = TTL_BUCKET_UPPER_BOUNDS_MS.find(([, upperBoundMs]) => ttlMs < upperBoundMs)
    buckets[bucket ? bucket[0] : 'over1y']++
}

/**
 * Yields SCAN batches, stopping once `limit` keys have been seen. Batches are trimmed to the
 * limit so callers can treat every yielded key as in scope.
 */
async function* scanBatches(
    redis: Redis,
    options: MaskerMigrationOptions,
    onLimitReached: () => void
): AsyncGenerator<string[]> {
    let cursor = '0'
    let seen = 0
    do {
        const [nextCursor, keys] = await redis.scan(cursor, 'MATCH', options.keyPattern, 'COUNT', options.scanCount)
        cursor = nextCursor
        if (keys.length === 0) {
            continue
        }
        const batch = options.limit === null ? keys : keys.slice(0, options.limit - seen)
        seen += batch.length
        if (batch.length > 0) {
            yield batch
        }
        if (options.limit !== null && seen >= options.limit) {
            onLimitReached()
            return
        }
        if (options.sleepMsBetweenBatches > 0) {
            await sleep(options.sleepMsBetweenBatches)
        }
    } while (cursor !== '0')
}

function successfulPipelineRows(rows: [Error | null, unknown][] | null, operation: string): [Error | null, unknown][] {
    if (!rows) {
        throw new Error(`${operation} returned no results`)
    }
    const failed = rows.find(([error]) => error)
    if (failed?.[0]) {
        throw new Error(`${operation} failed: ${failed[0].message}`)
    }
    return rows
}

function readValueAndTtl(rows: [Error | null, unknown][], index: number): { value: string | null; ttlMs: number } {
    return { value: (rows[index * 2]?.[1] ?? null) as string | null, ttlMs: Number(rows[index * 2 + 1]?.[1]) }
}

/**
 * Source-side census: how many masking keys exist, how many the target already holds, and how
 * long the rest have left. Cheaper than checkMaskerKeys because it never reads values.
 */
export async function collectMaskerStats(
    source: Redis,
    target: Redis,
    options: MaskerMigrationOptions,
    summary: MigrationSummary
): Promise<void> {
    for await (const keys of scanBatches(source, options, () => (summary.limitReached = true))) {
        summary.scannedSourceKeys += keys.length

        const sourcePipeline = source.pipeline()
        const targetPipeline = target.pipeline()
        for (const key of keys) {
            sourcePipeline.pttl(key)
            targetPipeline.exists(key)
        }
        const [sourceRows, targetRows] = await Promise.all([sourcePipeline.exec(), targetPipeline.exec()])
        const ttls = successfulPipelineRows(sourceRows, 'Source Redis expiry pipeline')
        const exists = successfulPipelineRows(targetRows, 'Target Valkey existence pipeline')

        keys.forEach((key, index) => {
            const ttlMs = Number(ttls[index]?.[1])
            // -2 means the key expired between SCAN returning it and this read.
            if (ttlMs === -2) {
                summary.skippedExpiredKeys++
                return
            }
            recordTtlBucket(summary.sourceTtlBuckets, ttlMs)
            if (Number(exists[index]?.[1]) === 1) {
                summary.presentInTarget++
                return
            }
            summary.missingFromTarget++
            recordSample(summary.samples.missingFromTarget, key, options.sampleKeysPerBucket)
        })
    }
}

/**
 * Creates the keys the target does not have yet, with SET NX so a counter the mirror is already
 * maintaining is never clobbered. That is what makes this safe to run repeatedly against live
 * writers, and why no writer pause is needed.
 */
export async function copyMissingMaskerKeys(
    source: Redis,
    target: Redis,
    options: MaskerMigrationOptions,
    summary: MigrationSummary
): Promise<void> {
    for await (const keys of scanBatches(source, options, () => (summary.limitReached = true))) {
        summary.scannedSourceKeys += keys.length

        const existsPipeline = target.pipeline()
        keys.forEach((key) => existsPipeline.exists(key))
        const exists = successfulPipelineRows(await existsPipeline.exec(), 'Target Valkey existence pipeline')
        const missing = keys.filter((_, index) => Number(exists[index]?.[1]) === 0)
        summary.presentInTarget += keys.length - missing.length
        if (missing.length === 0) {
            continue
        }

        const readPipeline = source.pipeline()
        for (const key of missing) {
            readPipeline.get(key)
            readPipeline.pttl(key)
        }
        const rows = successfulPipelineRows(await readPipeline.exec(), 'Source Redis read pipeline')

        const writes: { key: string; value: string; ttlMs: number }[] = []
        missing.forEach((key, index) => {
            const { value, ttlMs } = readValueAndTtl(rows, index)
            if (value === null || ttlMs === -2) {
                summary.skippedExpiredKeys++
                return
            }
            recordTtlBucket(summary.sourceTtlBuckets, ttlMs)
            recordSample(summary.samples.missingFromTarget, key, options.sampleKeysPerBucket)
            writes.push({ key, value, ttlMs })
        })
        summary.missingFromTarget += writes.length
        if (!options.execute || writes.length === 0) {
            continue
        }

        const writePipeline = target.pipeline()
        for (const { key, value, ttlMs } of writes) {
            if (ttlMs >= 0) {
                writePipeline.set(key, value, 'PX', ttlMs, 'NX')
            } else {
                writePipeline.set(key, value, 'NX')
            }
        }
        const writeRows = successfulPipelineRows(await writePipeline.exec(), 'Target Valkey write pipeline')
        // SET NX replies null when the mirror won the race and created the key, so this counts real writes.
        summary.copiedKeys += writeRows.filter(([, reply]) => reply === 'OK').length
    }
}

/** Counts keys the target holds that the source no longer has. Never deletes anything. */
async function countTargetOnlyKeys(
    source: Redis,
    target: Redis,
    options: MaskerMigrationOptions,
    summary: MigrationSummary
): Promise<void> {
    for await (const keys of scanBatches(target, options, () => (summary.limitReached = true))) {
        summary.scannedTargetKeys += keys.length
        const existsPipeline = source.pipeline()
        keys.forEach((key) => existsPipeline.exists(key))
        const exists = successfulPipelineRows(await existsPipeline.exec(), 'Source Redis existence pipeline')
        keys.forEach((key, index) => {
            if (Number(exists[index]?.[1]) !== 0) {
                return
            }
            summary.targetOnlyKeys++
            recordSample(summary.samples.targetOnly, key, options.sampleKeysPerBucket)
        })
    }
}

/**
 * Compares values and expiries in both directions and reports what differs. Read-only, so it
 * stays a reporting tool rather than a gate: finding drift never stops anything.
 */
export async function checkMaskerKeys(
    source: Redis,
    target: Redis,
    options: MaskerMigrationOptions,
    summary: MigrationSummary
): Promise<void> {
    for await (const keys of scanBatches(source, options, () => (summary.limitReached = true))) {
        summary.scannedSourceKeys += keys.length

        const sourcePipeline = source.pipeline()
        const targetPipeline = target.pipeline()
        for (const key of keys) {
            sourcePipeline.get(key)
            sourcePipeline.pttl(key)
            targetPipeline.get(key)
            targetPipeline.pttl(key)
        }
        const [sourceRowsRaw, targetRowsRaw] = await Promise.all([sourcePipeline.exec(), targetPipeline.exec()])
        const sourceRows = successfulPipelineRows(sourceRowsRaw, 'Source Redis verification pipeline')
        const targetRows = successfulPipelineRows(targetRowsRaw, 'Target Valkey verification pipeline')

        keys.forEach((key, index) => {
            const sourceEntry = readValueAndTtl(sourceRows, index)
            const targetEntry = readValueAndTtl(targetRows, index)
            if (sourceEntry.value === null) {
                summary.skippedExpiredKeys++
                return
            }
            recordTtlBucket(summary.sourceTtlBuckets, sourceEntry.ttlMs)
            if (targetEntry.value === null) {
                summary.missingFromTarget++
                recordSample(summary.samples.missingFromTarget, key, options.sampleKeysPerBucket)
                return
            }
            summary.presentInTarget++

            if (sourceEntry.value !== targetEntry.value) {
                summary.valueDrift++
                recordSample(summary.samples.valueDrift, key, options.sampleKeysPerBucket)
                const sourceCount = Number(sourceEntry.value)
                const targetCount = Number(targetEntry.value)
                if (Number.isFinite(sourceCount) && Number.isFinite(targetCount)) {
                    if (targetCount < sourceCount) {
                        summary.targetBehindSource++
                    } else {
                        summary.targetAheadOfSource++
                    }
                }
            }
            if (Math.abs(sourceEntry.ttlMs - targetEntry.ttlMs) > options.ttlToleranceMs) {
                summary.expiryDrift++
                recordSample(summary.samples.expiryDrift, key, options.sampleKeysPerBucket)
            }
        })
    }

    await countTargetOnlyKeys(source, target, options, summary)
}

export function migrationHasDrift(summary: MigrationSummary): boolean {
    return Boolean(summary.missingFromTarget || summary.valueDrift || summary.expiryDrift || summary.targetOnlyKeys)
}

export async function runMaskerMigration(
    source: Redis,
    target: Redis,
    options: MaskerMigrationOptions
): Promise<MigrationSummary> {
    if (!options.keyPattern.startsWith(MASK_KEY_PREFIX)) {
        throw new Error(`Key pattern must start with ${MASK_KEY_PREFIX}, got: ${options.keyPattern}`)
    }

    const summary = emptyMigrationSummary(options.phase, options.phase !== 'copy' || !options.execute)
    if (options.phase === 'stats') {
        await collectMaskerStats(source, target, options, summary)
    }
    if (options.phase === 'copy') {
        await copyMissingMaskerKeys(source, target, options, summary)
    }
    if (options.phase === 'check') {
        await checkMaskerKeys(source, target, options, summary)
    }
    return summary
}

function formatTtlBuckets(buckets: Record<TtlBucket, number>): string {
    return Object.entries(buckets)
        .filter(([, count]) => count > 0)
        .map(([bucket, count]) => `${bucket}=${count}`)
        .join(' ')
}

function formatSamples(label: string, keys: string[]): string[] {
    return keys.length > 0 ? [`  ${label} samples:`, ...keys.map((key) => `    ${key}`)] : []
}

export function formatMigrationSummary(summary: MigrationSummary, keyPattern: string): string {
    const lines = [
        `phase=${summary.phase} ${summary.dryRun ? '(read-only)' : '(writing)'} pattern=${keyPattern}`,
        `  source keys scanned:  ${summary.scannedSourceKeys}${summary.limitReached ? ' (limit reached, so these are a sample not a total)' : ''}`,
        `  already in target:    ${summary.presentInTarget}`,
        `  missing from target:  ${summary.missingFromTarget}`,
    ]
    if (summary.phase === 'copy') {
        lines.push(
            summary.dryRun
                ? `  would copy:           ${summary.missingFromTarget}`
                : `  copied:               ${summary.copiedKeys}`
        )
    }
    if (summary.skippedExpiredKeys > 0) {
        lines.push(`  expired mid-scan:     ${summary.skippedExpiredKeys}`)
    }
    if (summary.phase === 'check') {
        lines.push(
            `  value drift:          ${summary.valueDrift} (target behind ${summary.targetBehindSource}, ahead ${summary.targetAheadOfSource})`,
            `  expiry drift:         ${summary.expiryDrift}`,
            `  target keys scanned:  ${summary.scannedTargetKeys}`,
            `  target-only keys:     ${summary.targetOnlyKeys}`
        )
    }
    const ttlBuckets = formatTtlBuckets(summary.sourceTtlBuckets)
    if (ttlBuckets) {
        // Copy only reads expiries for the keys it is about to write, so the buckets describe those.
        const label = summary.phase === 'copy' ? 'missing, by lifetime' : 'source lifetimes'
        lines.push(`  ${label.padEnd(20)}  ${ttlBuckets}`)
    }
    lines.push(
        ...formatSamples('missing from target', summary.samples.missingFromTarget),
        ...formatSamples('value drift', summary.samples.valueDrift),
        ...formatSamples('expiry drift', summary.samples.expiryDrift),
        ...formatSamples('target-only', summary.samples.targetOnly)
    )
    return lines.join('\n')
}
