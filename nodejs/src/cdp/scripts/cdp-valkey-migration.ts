import { Redis } from 'ioredis'

type DumpBufferPipeline = ReturnType<Redis['pipeline']> & {
    dumpBuffer(key: string): ReturnType<Redis['pipeline']>
}

export type MigrationPhase = 'copy' | 'finalize' | 'verify'

export const CDP_MIGRATION_KEY_GROUPS = {
    'hog-masker': ['@posthog/hog-masker/mask/*'],
    'hog-watcher': [
        '@posthog/hog-watcher-2/state/*',
        '@posthog/hog-watcher-2/tokens/*',
        '@posthog/hog-watcher-2/state-lock/*',
    ],
} as const

export type CdpMigrationKeyGroup = keyof typeof CDP_MIGRATION_KEY_GROUPS

export function keyPatternsForGroups(groups: CdpMigrationKeyGroup[]): string[] {
    return [...new Set(groups.flatMap((group) => CDP_MIGRATION_KEY_GROUPS[group]))]
}

export type CdpMigrationOptions = {
    phase: MigrationPhase
    execute: boolean
    writersPaused: boolean
    requireWritersPaused: boolean
    scanCount: number
    ttlToleranceMs: number
    keyPatterns: string[]
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

async function* scanBatches(redis: Redis, keyPatterns: string[], count: number): AsyncGenerator<string[]> {
    for (const keyPattern of keyPatterns) {
        let cursor = '0'
        do {
            const [nextCursor, keys] = await redis.scan(cursor, 'MATCH', keyPattern, 'COUNT', count)
            cursor = nextCursor
            if (keys.length > 0) {
                yield keys
            }
        } while (cursor !== '0')
    }
}

function sourceTimeMs([seconds, microseconds]: [string, string]): number {
    return Number(seconds) * 1000 + Math.floor(Number(microseconds) / 1000)
}

export async function copyCdpKeys(
    source: Redis,
    target: Redis,
    options: CdpMigrationOptions,
    summary: MigrationSummary
): Promise<void> {
    for await (const keys of scanBatches(source, options.keyPatterns, options.scanCount)) {
        summary.sourceKeys += keys.length
        if (!options.execute) {
            continue
        }

        const sourcePipeline = source.pipeline() as DumpBufferPipeline
        for (const key of keys) {
            sourcePipeline.dumpBuffer(key)
            sourcePipeline.pttl(key)
        }
        const [time, rows] = await Promise.all([source.time(), sourcePipeline.exec()])
        if (!rows) {
            throw new Error('Source Redis pipeline returned no results')
        }

        const nowMs = sourceTimeMs(time)
        const targetPipeline = target.pipeline()
        keys.forEach((key, index) => {
            const value = rows[index * 2]?.[1] as Buffer | null
            const ttlMs = Number(rows[index * 2 + 1]?.[1])
            if (value === null || ttlMs === -2) {
                summary.skippedExpiredKeys++
                return
            }
            if (ttlMs === -1) {
                targetPipeline.restore(key, 0, value, 'REPLACE')
            } else if (ttlMs > 0) {
                targetPipeline.restore(key, nowMs + ttlMs, value, 'ABSTTL', 'REPLACE')
            } else {
                summary.skippedExpiredKeys++
                return
            }
            summary.copiedKeys++
        })
        await targetPipeline.exec()
    }
}

export async function deleteTargetExtras(
    source: Redis,
    target: Redis,
    options: CdpMigrationOptions,
    summary: MigrationSummary
): Promise<void> {
    for await (const keys of scanBatches(target, options.keyPatterns, options.scanCount)) {
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

export async function verifyCdpKeys(
    source: Redis,
    target: Redis,
    options: CdpMigrationOptions,
    summary: MigrationSummary
): Promise<void> {
    for await (const keys of scanBatches(source, options.keyPatterns, options.scanCount)) {
        const sourcePipeline = source.pipeline() as DumpBufferPipeline
        const targetPipeline = target.pipeline() as DumpBufferPipeline
        for (const key of keys) {
            sourcePipeline.dumpBuffer(key)
            sourcePipeline.pttl(key)
            targetPipeline.dumpBuffer(key)
            targetPipeline.pttl(key)
        }
        const [sourceRows, targetRows] = await Promise.all([sourcePipeline.exec(), targetPipeline.exec()])
        if (!sourceRows || !targetRows) {
            throw new Error('Verification pipeline returned no results')
        }
        keys.forEach((_, index) => {
            const sourceValue = sourceRows[index * 2]?.[1] as Buffer | null
            const sourceTtl = Number(sourceRows[index * 2 + 1]?.[1])
            const targetValue = targetRows[index * 2]?.[1] as Buffer | null
            const targetTtl = Number(targetRows[index * 2 + 1]?.[1])
            if (sourceValue === null || sourceTtl === -2) {
                return
            }
            if (targetValue === null) {
                summary.missingTargetKeys++
                return
            }
            if (!sourceValue.equals(targetValue)) {
                summary.mismatchedValues++
            }
            const expiryMismatch =
                sourceTtl === -1 || targetTtl === -1
                    ? sourceTtl !== targetTtl
                    : Math.abs(sourceTtl - targetTtl) > options.ttlToleranceMs
            if (expiryMismatch) {
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

export async function runCdpMigration(
    source: Redis,
    target: Redis,
    options: CdpMigrationOptions
): Promise<MigrationSummary> {
    if (options.phase === 'finalize' && !options.execute) {
        throw new Error('Finalization requires execute=true')
    }
    if (options.phase === 'finalize' && options.requireWritersPaused && !options.writersPaused) {
        throw new Error('Finalization for the selected key groups requires writersPaused=true')
    }

    const summary = emptyMigrationSummary()
    if (options.phase === 'copy' || options.phase === 'finalize') {
        await copyCdpKeys(source, target, options, summary)
    }
    if (options.phase === 'finalize') {
        await deleteTargetExtras(source, target, options, summary)
    }
    if (options.phase === 'verify' || options.phase === 'finalize') {
        await verifyCdpKeys(source, target, options, summary)
    }
    return summary
}
