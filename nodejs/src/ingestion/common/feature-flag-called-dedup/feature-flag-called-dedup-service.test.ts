import { IngestionLane } from '~/ingestion/config'
import { RedisPool } from '~/types'

import {
    RedisFeatureFlagCalledDedupService,
    createFeatureFlagCalledDedupService,
    featureFlagCalledDedupKey,
    parseFeatureFlagCalledDedupConfig,
} from './feature-flag-called-dedup-service'

interface MockRedis {
    pipeline: jest.Mock
    exec: jest.Mock
    set: jest.Mock
    get: jest.Mock
}

const createMockRedisPool = (
    execResults: [Error | null, unknown][] | null | Error
): { pool: RedisPool; redis: MockRedis } => {
    const pipeline = {
        set: jest.fn().mockReturnThis(),
        get: jest.fn().mockReturnThis(),
        exec:
            execResults instanceof Error
                ? jest.fn().mockRejectedValue(execResults)
                : jest.fn().mockResolvedValue(execResults),
    }
    const redis = {
        pipeline: jest.fn().mockReturnValue(pipeline),
        exec: pipeline.exec,
        set: pipeline.set,
        get: pipeline.get,
    }
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

        it('treats wildcard excluded teams as disabled', () => {
            const config = parseFeatureFlagCalledDedupConfig('drop', '*', '*', 600)

            expect(config.mode).toBe('disabled')
            expect(config.excludedTeams).toEqual([])
        })

        it('recognizes whitespace-padded wildcards', () => {
            const config = parseFeatureFlagCalledDedupConfig('drop', ' * ', ' * ', 600)

            expect(config.mode).toBe('disabled')
            expect(config.teams).toBe('*')
        })

        it.each([[0], [-5], [NaN]])('falls back to disabled on invalid ttl %p', (ttlSeconds) => {
            const config = parseFeatureFlagCalledDedupConfig('drop', '*', '', ttlSeconds)

            expect(config.mode).toBe('disabled')
        })
    })

    describe('createFeatureFlagCalledDedupService', () => {
        const envConfig = (mode: string, lane: IngestionLane | null = null) => ({
            INGESTION_LANE: lane,
            INGESTION_FEATURE_FLAG_CALLED_DEDUP_MODE: mode,
            INGESTION_FEATURE_FLAG_CALLED_DEDUP_TEAMS: '*',
            INGESTION_FEATURE_FLAG_CALLED_DEDUP_EXCLUDED_TEAMS: '',
            INGESTION_FEATURE_FLAG_CALLED_DEDUP_TTL_SECONDS: 3600,
        })

        it('returns undefined when disabled', () => {
            const { pool } = createMockRedisPool([])

            expect(createFeatureFlagCalledDedupService(pool, envConfig('disabled'))).toBeUndefined()
        })

        it('returns a service with the configured mode otherwise', () => {
            const { pool } = createMockRedisPool([])

            const service = createFeatureFlagCalledDedupService(pool, envConfig('drop'))

            expect(service).toBeInstanceOf(RedisFeatureFlagCalledDedupService)
            expect(service?.mode).toBe('drop')
        })

        it.each<[IngestionLane | null, boolean]>([
            ['main', true],
            ['overflow', true],
            ['turbo', true],
            ['team2', true],
            [null, true],
            ['historical', false],
            ['async', false],
        ])('lane %s yields a service: %s', (lane, expectService) => {
            const { pool } = createMockRedisPool([])

            const service = createFeatureFlagCalledDedupService(pool, envConfig('drop', lane))

            if (expectService) {
                expect(service).toBeInstanceOf(RedisFeatureFlagCalledDedupService)
            } else {
                expect(service).toBeUndefined()
            }
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
        it('has a compact, team-scannable shape', () => {
            // Key bytes are paid per live key at prod cardinality, so the
            // shape (short prefix, truncated digest) is a memory contract.
            expect(featureFlagCalledDedupKey(42, 'user-1', 'flag-a', 'variant-1', { org: 'o1' }, true)).toMatch(
                /^ffcd:42:[A-Za-z0-9_-]{22}$/
            )
        })

        it('is stable for the same tuple', () => {
            expect(featureFlagCalledDedupKey(1, 'user-1', 'flag-a', 'variant-1', { org: 'o1' }, true)).toBe(
                featureFlagCalledDedupKey(1, 'user-1', 'flag-a', 'variant-1', { org: 'o1' }, true)
            )
        })

        it('is independent of $groups property ordering', () => {
            expect(featureFlagCalledDedupKey(1, 'user-1', 'flag-a', true, { a: '1', b: '2' }, false)).toBe(
                featureFlagCalledDedupKey(1, 'user-1', 'flag-a', true, { b: '2', a: '1' }, false)
            )
        })

        type KeyArgs = Parameters<typeof featureFlagCalledDedupKey>
        it.each<[string, KeyArgs, KeyArgs]>([
            ['team', [1, 'user-1', 'flag-a', true, null, null], [2, 'user-1', 'flag-a', true, null, null]],
            ['distinct_id', [1, 'user-1', 'flag-a', true, null, null], [1, 'user-2', 'flag-a', true, null, null]],
            ['flag', [1, 'user-1', 'flag-a', true, null, null], [1, 'user-1', 'flag-b', true, null, null]],
            ['response', [1, 'user-1', 'flag-a', true, null, null], [1, 'user-1', 'flag-a', false, null, null]],
            [
                'response null vs "null"',
                [1, 'user-1', 'flag-a', null, null, null],
                [1, 'user-1', 'flag-a', 'null', null, null],
            ],
            [
                'groups',
                [1, 'user-1', 'flag-a', true, { org: 'o1' }, null],
                [1, 'user-1', 'flag-a', true, { org: 'o2' }, null],
            ],
            [
                'groups vs none',
                [1, 'user-1', 'flag-a', true, { org: 'o1' }, null],
                [1, 'user-1', 'flag-a', true, undefined, null],
            ],
            // false and null/undefined both mean "not an experiment exposure" — the key
            // only distinguishes true (experiment) from everything else.
            ['has_experiment', [1, 'user-1', 'flag-a', true, null, true], [1, 'user-1', 'flag-a', true, null, null]],
            [
                'has_experiment true vs absent',
                [1, 'user-1', 'flag-a', true, null, true],
                [1, 'user-1', 'flag-a', true, null, undefined],
            ],
            // The delimiter-injection collision class: components must not concatenate
            ['component boundary', [1, 'user:1', 'flag', true, null, null], [1, 'user', ':1flag', true, null, null]],
        ])('differs by %s', (_label, a, b) => {
            expect(featureFlagCalledDedupKey(...a)).not.toBe(featureFlagCalledDedupKey(...b))
        })
    })

    describe('claimKeys', () => {
        it('returns empty for no claims', async () => {
            const { service, redis } = createService([])

            expect(await service.claimKeys([])).toEqual([])
            expect(redis.pipeline).not.toHaveBeenCalled()
        })

        it('maps fresh claims to true and foreign claims to false', async () => {
            const { service, redis } = createService([
                [null, 'OK'],
                [null, 'uuid-1'],
                [null, null],
                [null, 'other-uuid'],
            ])

            expect(
                await service.claimKeys([
                    { key: 'key-1', claimId: 'uuid-1' },
                    { key: 'key-2', claimId: 'uuid-2' },
                ])
            ).toEqual([true, false])
            expect(redis.set).toHaveBeenCalledWith('key-1', 'uuid-1', 'EX', 3600, 'NX')
            expect(redis.set).toHaveBeenCalledWith('key-2', 'uuid-2', 'EX', 3600, 'NX')
            expect(redis.get).toHaveBeenCalledWith('key-1')
            expect(redis.get).toHaveBeenCalledWith('key-2')
        })

        it('recognizes its own prior claim on redelivery', async () => {
            // SET NX loses to the claim made by a previous delivery of the same
            // event, but the stored claim id matches, so the event still passes.
            const { service } = createService([
                [null, null],
                [null, 'uuid-1'],
            ])

            expect(await service.claimKeys([{ key: 'key-1', claimId: 'uuid-1' }])).toEqual([true])
        })

        it('resolves duplicate keys within one call in order', async () => {
            // Redis executes pipelined commands sequentially, so the first
            // occurrence of a repeated key claims it and later ones read the
            // first occurrence's claim id.
            const { service, redis } = createService([
                [null, 'OK'],
                [null, 'uuid-a'],
                [null, null],
                [null, 'uuid-a'],
            ])

            expect(
                await service.claimKeys([
                    { key: 'key-1', claimId: 'uuid-a' },
                    { key: 'key-1', claimId: 'uuid-b' },
                ])
            ).toEqual([true, false])
            expect(redis.set).toHaveBeenCalledTimes(2)
        })

        it('fails open when the pipeline throws', async () => {
            const { service } = createService(new Error('redis down'))

            expect(
                await service.claimKeys([
                    { key: 'key-1', claimId: 'uuid-1' },
                    { key: 'key-2', claimId: 'uuid-2' },
                ])
            ).toEqual([true, true])
        })

        it('fails open when the pipeline returns no results', async () => {
            const { service } = createService(null)

            expect(await service.claimKeys([{ key: 'key-1', claimId: 'uuid-1' }])).toEqual([true])
        })

        it('fails open when the pipeline returns the wrong number of results', async () => {
            const { service } = createService([[null, 'OK']])

            expect(await service.claimKeys([{ key: 'key-1', claimId: 'uuid-1' }])).toEqual([true])
        })

        it('fails open per claim on SET command errors', async () => {
            const { service } = createService([
                [new Error('boom'), null],
                [null, 'other-uuid'],
                [null, null],
                [null, 'other-uuid'],
            ])

            expect(
                await service.claimKeys([
                    { key: 'key-1', claimId: 'uuid-1' },
                    { key: 'key-2', claimId: 'uuid-2' },
                ])
            ).toEqual([true, false])
        })

        it('fails open per claim on GET command errors', async () => {
            const { service } = createService([
                [null, null],
                [new Error('boom'), null],
            ])

            expect(await service.claimKeys([{ key: 'key-1', claimId: 'uuid-1' }])).toEqual([true])
        })

        it('fails open when the key disappears between SET and GET', async () => {
            // The pipeline is not atomic: the key existed at SET time (NX
            // lost) but expired or was evicted before the GET. No claim
            // present means no evidence of a duplicate.
            const { service } = createService([
                [null, null],
                [null, null],
            ])

            expect(await service.claimKeys([{ key: 'key-1', claimId: 'uuid-1' }])).toEqual([true])
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

            expect(await service.claimKeys([{ key: 'key-1', claimId: 'uuid-1' }])).toEqual([true])
        })
    })
})
