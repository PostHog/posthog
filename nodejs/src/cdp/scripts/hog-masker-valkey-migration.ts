import { Redis } from 'ioredis'

export type MigrationPhase = 'copy' | 'finalize' | 'verify'

export type MaskerMigrationOptions = {
    phase: MigrationPhase
    execute: boolean
    writersPaused: boolean
    scanCount: number
    ttlToleranceMs: number
    keyPattern: string
}

export type MigrationSummary = {
    sourceKeys: number
    copiedKeys: number
    skippedExpiredKeys: number
    deletedExtraKeys: number
    mismatchedValues: number
    mismatchedExpiries: number
    missingTargetKeys: number
    extraTargetKeys: number
}

export function emptyMigrationSummary(): MigrationSummary {
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

async function* scanBatches(redis: Redis, keyPattern: string, count: number): AsyncGenerator<string[]> {
    let cursor = '0'
    do {
        const [nextCursor, keys] = await redis.scan(cursor, 'MATCH', keyPattern, 'COUNT', count)
        cursor = nextCursor
        if (keys.length > 0) {
            yield keys
        }
    } while (cursor !== '0')
}

function sourceTimeMs([seconds, microseconds]: [string, string]): number {
    return Number(seconds) * 1000 + Math.floor(Number(microseconds) / 1000)
}

export async function copyMaskerKeys(
    source: Redis,
    target: Redis,
    options: MaskerMigrationOptions,
    summary: MigrationSummary
): Promise<void> {
    for await (const keys of scanBatches(source, options.keyPattern, options.scanCount)) {
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

export async function deleteTargetExtras(
    source: Redis,
    target: Redis,
    options: MaskerMigrationOptions,
    summary: MigrationSummary
): Promise<void> {
    for await (const keys of scanBatches(target, options.keyPattern, options.scanCount)) {
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

export async function verifyMaskerKeys(
    source: Redis,
    target: Redis,
    options: MaskerMigrationOptions,
    summary: MigrationSummary
): Promise<void> {
    for await (const keys of scanBatches(source, options.keyPattern, options.scanCount)) {
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

export function migrationHasMismatches(summary: MigrationSummary): boolean {
    return Boolean(
        summary.mismatchedValues ||
            summary.mismatchedExpiries ||
            summary.missingTargetKeys ||
            summary.extraTargetKeys - summary.deletedExtraKeys > 0
    )
}

export async function runMaskerMigration(
    source: Redis,
    target: Redis,
    options: MaskerMigrationOptions
): Promise<MigrationSummary> {
    if (options.phase === 'finalize' && (!options.execute || !options.writersPaused)) {
        throw new Error('Finalization requires execute=true and writersPaused=true')
    }

    const summary = emptyMigrationSummary()
    if (options.phase === 'copy' || options.phase === 'finalize') {
        await copyMaskerKeys(source, target, options, summary)
    }
    if (options.phase === 'finalize') {
        await deleteTargetExtras(source, target, options, summary)
    }
    if (options.phase === 'verify' || options.phase === 'finalize') {
        await verifyMaskerKeys(source, target, options, summary)
    }
    return summary
}
