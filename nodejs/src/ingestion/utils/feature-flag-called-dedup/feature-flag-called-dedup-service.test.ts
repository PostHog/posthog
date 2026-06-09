import { RedisPool } from '../../../types'
import {
    RedisFeatureFlagCalledDedupService,
    featureFlagCalledDedupKey,
    parseFeatureFlagCalledDedupConfig,
} from './feature-flag-called-dedup-service'

interface MockRedis {
    pipeline: jest.Mock
    exec: jest.Mock
    set: jest.Mock
}

const createMockRedisPool = (
    execResults: [Error | null, unknown][] | null | Error
): { pool: RedisPool; redis: MockRedis } => {
    const pipeline = {
        set: jest.fn().mockReturnThis(),
        exec:
            execResults instanceof Error
                ? jest.fn().mockRejectedValue(execResults)
                : jest.fn().mockResolvedValue(execResults),
    }
    const redis = { pipeline: jest.fn().mockReturnValue(pipeline), exec: pipeline.exec, set: pipeline.set }
    const pool = {
        acquire: jest.fn().mockResolvedValue(redis),
        release: jest.fn().mockResolvedValue(undefined),
    } as unknown as RedisPool
    return { pool, redis }
}

const createService = (execResults: [Error | null, unknown][] | null | Error) => {
    const { pool, redis } = createMockRedisPool(execResults)
    const service = new RedisFeatureFlagCalledDedupService({
        redisPool: pool,
        config: parseFeatureFlagCalledDedupConfig('drop', '*', '', 3600),
    })
    return { service, redis }
}

describe('RedisFeatureFlagCalledDedupService', () => {
    describe('parseFeatureFlagCalledDedupConfig', () => {
        it('parses a full config', () => {
            const config = parseFeatureFlagCalledDedupConfig('shadow', '1,2,3', '4', 600)

            expect(config).toEqual({ mode: 'shadow', teams: [1, 2, 3], excludedTeams: [4], ttlSeconds: 600 })
        })

        it('parses wildcard teams', () => {
            const config = parseFeatureFlagCalledDedupConfig('drop', '*', '', 600)

            expect(config.teams).toBe('*')
            expect(config.excludedTeams).toEqual([])
        })

        it('falls back to disabled on an invalid mode', () => {
            const config = parseFeatureFlagCalledDedupConfig('garbage', '*', '', 600)

            expect(config.mode).toBe('disabled')
        })
    })

    describe('isEnabledForTeam', () => {
        it.each([
            ['*', '', 5, true],
            ['*', '5', 5, false],
            ['1,2', '', 2, true],
            ['1,2', '', 3, false],
            ['1,2', '2', 2, false],
            ['', '', 1, false],
        ])('teams=%s excluded=%s team=%i -> %s', (teams, excluded, teamId, expected) => {
            const { pool } = createMockRedisPool([])
            const service = new RedisFeatureFlagCalledDedupService({
                redisPool: pool,
                config: parseFeatureFlagCalledDedupConfig('drop', teams, excluded, 3600),
            })

            expect(service.isEnabledForTeam(teamId)).toBe(expected)
        })
    })

    describe('featureFlagCalledDedupKey', () => {
        it('is stable for the same tuple', () => {
            expect(featureFlagCalledDedupKey(1, 'user-1', 'flag-a', 'variant-1', { org: 'o1' })).toBe(
                featureFlagCalledDedupKey(1, 'user-1', 'flag-a', 'variant-1', { org: 'o1' })
            )
        })

        it('is independent of $groups property ordering', () => {
            expect(featureFlagCalledDedupKey(1, 'user-1', 'flag-a', true, { a: '1', b: '2' })).toBe(
                featureFlagCalledDedupKey(1, 'user-1', 'flag-a', true, { b: '2', a: '1' })
            )
        })

        it.each([
            ['team', [1, 'user-1', 'flag-a', true, null], [2, 'user-1', 'flag-a', true, null]],
            ['distinct_id', [1, 'user-1', 'flag-a', true, null], [1, 'user-2', 'flag-a', true, null]],
            ['flag', [1, 'user-1', 'flag-a', true, null], [1, 'user-1', 'flag-b', true, null]],
            ['response', [1, 'user-1', 'flag-a', true, null], [1, 'user-1', 'flag-a', false, null]],
            ['response null vs "null"', [1, 'user-1', 'flag-a', null, null], [1, 'user-1', 'flag-a', 'null', null]],
            ['groups', [1, 'user-1', 'flag-a', true, { org: 'o1' }], [1, 'user-1', 'flag-a', true, { org: 'o2' }]],
            ['groups vs none', [1, 'user-1', 'flag-a', true, { org: 'o1' }], [1, 'user-1', 'flag-a', true, undefined]],
            // The delimiter-injection collision class: components must not concatenate
            ['component boundary', [1, 'user:1', 'flag', true, null], [1, 'user', ':1flag', true, null]],
        ])('differs by %s', (_label, a, b) => {
            const [teamA, distinctA, flagA, responseA, groupsA] = a
            const [teamB, distinctB, flagB, responseB, groupsB] = b

            expect(
                featureFlagCalledDedupKey(teamA as number, distinctA as string, flagA as string, responseA, groupsA)
            ).not.toBe(
                featureFlagCalledDedupKey(teamB as number, distinctB as string, flagB as string, responseB, groupsB)
            )
        })
    })

    describe('claimKeys', () => {
        it('returns empty for no keys', async () => {
            const { service, redis } = createService([])

            expect(await service.claimKeys([])).toEqual([])
            expect(redis.pipeline).not.toHaveBeenCalled()
        })

        it('maps OK replies to claimed and null replies to duplicates', async () => {
            const { service, redis } = createService([
                [null, 'OK'],
                [null, null],
            ])

            expect(await service.claimKeys(['key-1', 'key-2'])).toEqual([true, false])
            expect(redis.set).toHaveBeenCalledWith('key-1', '1', 'EX', 3600, 'NX')
            expect(redis.set).toHaveBeenCalledWith('key-2', '1', 'EX', 3600, 'NX')
        })

        it('resolves duplicate keys within one call in order', async () => {
            // Redis executes pipelined SET NX commands sequentially, so the first
            // occurrence of a repeated key replies 'OK' and later ones reply null.
            const { service, redis } = createService([
                [null, 'OK'],
                [null, null],
            ])

            expect(await service.claimKeys(['key-1', 'key-1'])).toEqual([true, false])
            expect(redis.set).toHaveBeenCalledTimes(2)
        })

        it('fails open when the pipeline throws', async () => {
            const { service } = createService(new Error('redis down'))

            expect(await service.claimKeys(['key-1', 'key-2'])).toEqual([true, true])
        })

        it('fails open when the pipeline returns no results', async () => {
            const { service } = createService(null)

            expect(await service.claimKeys(['key-1'])).toEqual([true])
        })

        it('fails open per command on command errors', async () => {
            const { service } = createService([
                [new Error('boom'), null],
                [null, null],
            ])

            expect(await service.claimKeys(['key-1', 'key-2'])).toEqual([true, false])
        })

        it('fails open when acquiring a client fails', async () => {
            const pool = {
                acquire: jest.fn().mockRejectedValue(new Error('pool exhausted')),
                release: jest.fn(),
            } as unknown as RedisPool
            const service = new RedisFeatureFlagCalledDedupService({
                redisPool: pool,
                config: parseFeatureFlagCalledDedupConfig('drop', '*', '', 3600),
            })

            expect(await service.claimKeys(['key-1'])).toEqual([true])
        })
    })
})
