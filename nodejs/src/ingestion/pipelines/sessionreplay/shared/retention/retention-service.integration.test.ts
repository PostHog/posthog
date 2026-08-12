import { defaultConfig } from '~/common/config/config'
import { createIngestionRedisConnectionConfig } from '~/common/config/redis-pools'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { createRedisPoolFromConfig } from '~/common/utils/db/redis'
import { ValidRetentionPeriods } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { TeamService } from '~/ingestion/pipelines/sessionreplay/shared/teams/team-service'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { RedisPool } from '~/types'

import { RetentionService } from './retention-service'

describe('RetentionService (integration)', () => {
    let redisPool: RedisPool
    let postgres: PostgresRouter
    let teamId: number

    beforeEach(async () => {
        await resetTestDatabase()
        postgres = new PostgresRouter(defaultConfig)
        teamId = (await getFirstTeam(postgres)).id // seeded with retention '30d'

        redisPool = createRedisPoolFromConfig({
            connection: createIngestionRedisConnectionConfig(defaultConfig),
            poolMinSize: 1,
            poolMaxSize: 3,
        })
    })

    afterEach(async () => {
        await redisPool.drain()
        await redisPool.clear()
        await postgres.end()
    })

    const setTeamRetention = async (period: string): Promise<void> => {
        await postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_team SET session_recording_retention_period = $1 WHERE id = $2`,
            [period, teamId],
            'test-set-retention'
        )
    }

    it('resolves via the team service on a miss, then serves the second lookup from Redis', async () => {
        const teamService = new TeamService(postgres) // team service is Postgres-backed
        const getRetentionSpy = jest.spyOn(teamService, 'getRetentionPeriodByTeamId')
        const service = new RetentionService(redisPool, teamService)
        const sessionId = `it-hit-${Date.now()}` // unique so the first lookup is a real cache miss

        const first = await service.resolveSessionRetentions(new SessionSet().add(teamId, sessionId))
        expect(first.get(teamId, sessionId)).toEqual({ resolved: true, retentionPeriod: '30d' })

        const second = await service.resolveSessionRetentions(new SessionSet().add(teamId, sessionId))
        expect(second.get(teamId, sessionId)).toEqual({ resolved: true, retentionPeriod: '30d' })

        // The team service is consulted once; the second lookup is served from Redis.
        expect(getRetentionSpy).toHaveBeenCalledTimes(1)
    })

    it('marks a session unresolvable when the team has no retention, and does not cache the miss', async () => {
        const teamService = new TeamService(postgres)
        const getRetentionSpy = jest.spyOn(teamService, 'getRetentionPeriodByTeamId')
        const service = new RetentionService(redisPool, teamService)
        const unknownTeamId = 9_999_999
        const sessionId = `it-null-${Date.now()}`

        const first = await service.resolveSessionRetentions(new SessionSet().add(unknownTeamId, sessionId))
        expect(first.get(unknownTeamId, sessionId)).toEqual({ resolved: false })

        // A null retention is not written to Redis, so the second lookup consults the team service
        // again rather than serving a stale miss from the cache.
        const second = await service.resolveSessionRetentions(new SessionSet().add(unknownTeamId, sessionId))
        expect(second.get(unknownTeamId, sessionId)).toEqual({ resolved: false })
        expect(getRetentionSpy).toHaveBeenCalledTimes(2)
    })

    // Every allowed period must resolve and round-trip through Redis; driven off the authoritative set.
    it.each([...ValidRetentionPeriods])('resolves retention %s end-to-end (team service -> Redis)', async (period) => {
        await setTeamRetention(period)
        const service = new RetentionService(redisPool, new TeamService(postgres))
        const sessionId = `it-matrix-${period}-${Date.now()}`

        const result = await service.resolveSessionRetentions(new SessionSet().add(teamId, sessionId))
        expect(result.get(teamId, sessionId)).toEqual({ resolved: true, retentionPeriod: period })
    })
})
