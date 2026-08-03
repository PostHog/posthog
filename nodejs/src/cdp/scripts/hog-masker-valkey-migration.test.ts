import IORedis, { Redis } from 'ioredis'

import { MaskerMigrationOptions, migrationHasMismatches, runMaskerMigration } from './hog-masker-valkey-migration'

const KEY_PATTERN = '@posthog-test/hog-masker/mask/*'
const SOURCE_KEY = '@posthog-test/hog-masker/mask/function/hash'
const EXTRA_KEY = '@posthog-test/hog-masker/mask/extra/hash'

describe('HogMasker Valkey migration', () => {
    let source: Redis
    let target: Redis

    const options = (overrides: Partial<MaskerMigrationOptions> = {}): MaskerMigrationOptions => ({
        phase: 'copy',
        execute: true,
        writersPaused: false,
        scanCount: 10,
        ttlToleranceMs: 500,
        keyPattern: KEY_PATTERN,
        ...overrides,
    })

    beforeAll(async () => {
        // This suite runs against the local Redis test container; production connections come from CDP_* env vars.
        // nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
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

        const summary = await runMaskerMigration(source, target, options({ execute: false }))

        expect(summary).toMatchObject({ sourceKeys: 1, copiedKeys: 0 })
        await expect(target.get(SOURCE_KEY)).resolves.toBeNull()
    })

    it('copies values while preserving the absolute expiry', async () => {
        await source.set(SOURCE_KEY, '42', 'PX', 60_000)

        const summary = await runMaskerMigration(source, target, options())
        const [sourceTtl, targetTtl] = await Promise.all([source.pttl(SOURCE_KEY), target.pttl(SOURCE_KEY)])

        expect(summary).toMatchObject({ sourceKeys: 1, copiedKeys: 1 })
        await expect(target.get(SOURCE_KEY)).resolves.toBe('42')
        expect(Math.abs(sourceTtl - targetTtl)).toBeLessThan(500)
    })

    it('finalizes an identical target and removes target-only keys', async () => {
        await source.set(SOURCE_KEY, '42', 'PX', 60_000)
        await target.set(EXTRA_KEY, '1', 'PX', 60_000)

        const summary = await runMaskerMigration(source, target, options({ phase: 'finalize', writersPaused: true }))

        expect(summary).toMatchObject({ copiedKeys: 1, deletedExtraKeys: 1, missingTargetKeys: 0 })
        expect(migrationHasMismatches(summary)).toBe(false)
        await expect(target.get(EXTRA_KEY)).resolves.toBeNull()
    })

    it('detects missing, different, and differently expiring target keys', async () => {
        await source.set(SOURCE_KEY, '42', 'PX', 60_000)
        await target.set(SOURCE_KEY, '7', 'PX', 30_000)
        await target.set(EXTRA_KEY, '1', 'PX', 60_000)

        const summary = await runMaskerMigration(
            source,
            target,
            options({ phase: 'verify', execute: false, ttlToleranceMs: 100 })
        )

        expect(summary).toMatchObject({ mismatchedValues: 1, mismatchedExpiries: 1, extraTargetKeys: 1 })
        expect(migrationHasMismatches(summary)).toBe(true)
    })

    it('refuses to finalize without paused writers', async () => {
        await expect(
            runMaskerMigration(source, target, options({ phase: 'finalize', writersPaused: false }))
        ).rejects.toThrow('Finalization requires execute=true and writersPaused=true')
    })
})
