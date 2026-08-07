import IORedis, { Redis } from 'ioredis'

import { MASK_KEY_PREFIX } from '../services/monitoring/hog-masker.keys'
import {
    DEFAULT_KEY_PATTERN,
    MaskerMigrationOptions,
    migrationHasDrift,
    runMaskerMigration,
} from './hog-masker-valkey-migration'

const SOURCE_KEY = `${MASK_KEY_PREFIX}function/hash`
const MISSING_KEY = `${MASK_KEY_PREFIX}function/missing`
const EXPIRY_KEY = `${MASK_KEY_PREFIX}function/expiry`
const TARGET_ONLY_KEY = `${MASK_KEY_PREFIX}function/target-only`

describe('HogMasker Valkey migration', () => {
    let source: Redis
    let target: Redis

    const options = (overrides: Partial<MaskerMigrationOptions> = {}): MaskerMigrationOptions => ({
        phase: 'copy',
        execute: true,
        keyPattern: DEFAULT_KEY_PATTERN,
        scanCount: 10,
        limit: null,
        sleepMsBetweenBatches: 0,
        ttlToleranceMs: 500,
        sampleKeysPerBucket: 5,
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

    it('refuses a key pattern outside the masker prefix', async () => {
        await expect(runMaskerMigration(source, target, options({ keyPattern: '*' }))).rejects.toThrow(
            `Key pattern must start with ${MASK_KEY_PREFIX}`
        )
    })

    it('reports the copy it would make without writing anything', async () => {
        await source.set(SOURCE_KEY, '42', 'PX', 60_000)

        const summary = await runMaskerMigration(source, target, options({ execute: false }))

        expect(summary).toMatchObject({ dryRun: true, scannedSourceKeys: 1, missingFromTarget: 1, copiedKeys: 0 })
        await expect(target.get(SOURCE_KEY)).resolves.toBeNull()
    })

    it('copies missing keys while preserving the remaining expiry', async () => {
        await source.set(SOURCE_KEY, '42', 'PX', 60_000)

        const summary = await runMaskerMigration(source, target, options())
        const [sourceTtl, targetTtl] = await Promise.all([source.pttl(SOURCE_KEY), target.pttl(SOURCE_KEY)])

        expect(summary).toMatchObject({ scannedSourceKeys: 1, missingFromTarget: 1, copiedKeys: 1 })
        await expect(target.get(SOURCE_KEY)).resolves.toBe('42')
        expect(Math.abs(sourceTtl - targetTtl)).toBeLessThan(500)
    })

    it('leaves a counter the target already holds untouched', async () => {
        await source.set(SOURCE_KEY, '42', 'PX', 60_000)
        await target.set(SOURCE_KEY, '7', 'PX', 30_000)

        const summary = await runMaskerMigration(source, target, options())

        expect(summary).toMatchObject({ presentInTarget: 1, missingFromTarget: 0, copiedKeys: 0 })
        await expect(target.get(SOURCE_KEY)).resolves.toBe('7')
        expect(await target.pttl(SOURCE_KEY)).toBeLessThanOrEqual(30_000)
    })

    it('stops at the limit and marks the counts as a sample', async () => {
        for (let index = 0; index < 25; index++) {
            await source.set(`${MASK_KEY_PREFIX}function/${index}`, '1', 'PX', 60_000)
        }

        const summary = await runMaskerMigration(source, target, options({ phase: 'stats', execute: false, limit: 5 }))

        expect(summary).toMatchObject({ scannedSourceKeys: 5, missingFromTarget: 5, limitReached: true })
        expect(summary.sourceTtlBuckets.under1h).toBe(5)
    })

    it('reports drift in both directions without deleting anything', async () => {
        await source.set(SOURCE_KEY, '42', 'PX', 60_000)
        await target.set(SOURCE_KEY, '7', 'PX', 60_000)
        await source.set(MISSING_KEY, '1', 'PX', 60_000)
        await source.set(EXPIRY_KEY, '1', 'PX', 60_000)
        await target.set(EXPIRY_KEY, '1', 'PX', 30_000)
        await target.set(TARGET_ONLY_KEY, '1', 'PX', 60_000)

        const summary = await runMaskerMigration(
            source,
            target,
            options({ phase: 'check', execute: false, ttlToleranceMs: 100 })
        )

        expect(summary).toMatchObject({
            scannedSourceKeys: 3,
            scannedTargetKeys: 3,
            missingFromTarget: 1,
            valueDrift: 1,
            targetBehindSource: 1,
            expiryDrift: 1,
            targetOnlyKeys: 1,
        })
        expect(migrationHasDrift(summary)).toBe(true)
        await expect(target.exists(TARGET_ONLY_KEY)).resolves.toBe(1)
    })
})
