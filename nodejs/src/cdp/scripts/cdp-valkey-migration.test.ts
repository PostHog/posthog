import IORedis, { Redis } from 'ioredis'

import {
    CdpMigrationOptions,
    keyPatternsForGroups,
    migrationHasMismatches,
    runCdpMigration,
} from './cdp-valkey-migration'

const KEY_PATTERNS = ['@posthog-test/hog-masker/mask/*', '@posthog-test/hog-watcher-2/*']
const SOURCE_KEY = '@posthog-test/hog-masker/mask/function/hash'
const EXTRA_KEY = '@posthog-test/hog-masker/mask/extra/hash'
const WATCHER_STATE_KEY = '@posthog-test/hog-watcher-2/state/function'
const WATCHER_TOKENS_KEY = '@posthog-test/hog-watcher-2/tokens/function'

describe('CDP Valkey migration', () => {
    let source: Redis
    let target: Redis

    const options = (overrides: Partial<CdpMigrationOptions> = {}): CdpMigrationOptions => ({
        phase: 'copy',
        execute: true,
        writersPaused: false,
        requireWritersPaused: true,
        scanCount: 10,
        ttlToleranceMs: 500,
        keyPatterns: KEY_PATTERNS,
        ...overrides,
    })

    beforeAll(async () => {
        const redisUrl = process.env.REDIS_URL || 'redis://127.0.0.1:6379'
        source = new IORedis(redisUrl, { db: 14 })
        target = new IORedis(redisUrl, { db: 15 })
        await Promise.all([source.ping(), target.ping()])
    })

    beforeEach(async () => {
        await Promise.all([source.flushdb(), target.flushdb()])
    })

    afterAll(async () => {
        await Promise.all([source.quit(), target.quit()])
    })

    it('keeps dry-run copy read-only', async () => {
        await source.set(SOURCE_KEY, '42', 'PX', 60_000)

        const summary = await runCdpMigration(source, target, options({ execute: false }))

        expect(summary).toMatchObject({ sourceKeys: 1, copiedKeys: 0 })
        await expect(target.get(SOURCE_KEY)).resolves.toBeNull()
    })

    it('copies values while preserving the absolute expiry', async () => {
        await source.set(SOURCE_KEY, '42', 'PX', 60_000)

        const summary = await runCdpMigration(source, target, options())
        const [sourceTtl, targetTtl] = await Promise.all([source.pttl(SOURCE_KEY), target.pttl(SOURCE_KEY)])

        expect(summary).toMatchObject({ sourceKeys: 1, copiedKeys: 1 })
        await expect(target.get(SOURCE_KEY)).resolves.toBe('42')
        expect(Math.abs(sourceTtl - targetTtl)).toBeLessThan(500)
    })

    it('finalizes an identical target and removes target-only keys', async () => {
        await source.set(SOURCE_KEY, '42', 'PX', 60_000)
        await target.set(EXTRA_KEY, '1', 'PX', 60_000)

        const summary = await runCdpMigration(source, target, options({ phase: 'finalize', writersPaused: true }))

        expect(summary).toMatchObject({ copiedKeys: 1, deletedExtraKeys: 1, missingTargetKeys: 0 })
        expect(migrationHasMismatches(summary)).toBe(false)
        await expect(target.get(EXTRA_KEY)).resolves.toBeNull()
    })

    it('detects missing, different, and differently expiring target keys', async () => {
        await source.set(SOURCE_KEY, '42', 'PX', 60_000)
        await target.set(SOURCE_KEY, '7', 'PX', 30_000)
        await target.set(EXTRA_KEY, '1', 'PX', 60_000)

        const summary = await runCdpMigration(
            source,
            target,
            options({ phase: 'verify', execute: false, ttlToleranceMs: 100 })
        )

        expect(summary).toMatchObject({ mismatchedValues: 1, mismatchedExpiries: 1, extraTargetKeys: 1 })
        expect(migrationHasMismatches(summary)).toBe(true)
    })

    it('refuses to finalize without paused writers', async () => {
        await expect(
            runCdpMigration(source, target, options({ phase: 'finalize', writersPaused: false }))
        ).rejects.toThrow('Finalization for the selected key groups requires writersPaused=true')
    })

    it('allows a one-shot live finalization for watcher-only state', async () => {
        await source.set(WATCHER_STATE_KEY, '12')

        const summary = await runCdpMigration(
            source,
            target,
            options({
                phase: 'finalize',
                keyPatterns: keyPatternsForGroups(['hog-watcher']).map((pattern) => pattern.replace('@posthog/', '@posthog-test/')),
                requireWritersPaused: false,
            })
        )

        expect(migrationHasMismatches(summary)).toBe(false)
        await expect(target.get(WATCHER_STATE_KEY)).resolves.toBe('12')
    })

    it('selects masker and watcher key groups independently', () => {
        expect(keyPatternsForGroups(['hog-masker'])).toEqual(['@posthog/hog-masker/mask/*'])
        expect(keyPatternsForGroups(['hog-watcher'])).toEqual([
            '@posthog/hog-watcher-2/state/*',
            '@posthog/hog-watcher-2/tokens/*',
            '@posthog/hog-watcher-2/state-lock/*',
        ])
    })

    it('copies non-expiring watcher state', async () => {
        await source.set(WATCHER_STATE_KEY, '12')

        const summary = await runCdpMigration(source, target, options())

        expect(summary).toMatchObject({ copiedKeys: 1, skippedExpiredKeys: 0 })
        await expect(target.get(WATCHER_STATE_KEY)).resolves.toBe('12')
        await expect(target.pttl(WATCHER_STATE_KEY)).resolves.toBe(-1)
    })

    it('copies watcher hash values with their absolute expiry', async () => {
        await source.hset(WATCHER_TOKENS_KEY, { pool: '42', ts: '1234' })
        await source.pexpire(WATCHER_TOKENS_KEY, 60_000)

        await runCdpMigration(source, target, options())
        const [sourceTtl, targetTtl] = await Promise.all([
            source.pttl(WATCHER_TOKENS_KEY),
            target.pttl(WATCHER_TOKENS_KEY),
        ])

        await expect(target.hgetall(WATCHER_TOKENS_KEY)).resolves.toEqual({ pool: '42', ts: '1234' })
        expect(Math.abs(sourceTtl - targetTtl)).toBeLessThan(500)
    })
})
