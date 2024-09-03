import Redis from 'ioredis'
import { Pool } from 'pg'

import { Hub } from '../../../src/types'
import { DependencyUnavailableError } from '../../../src/utils/db/error'
import { createHub } from '../../../src/utils/db/hub'
import { PostgresUse } from '../../../src/utils/db/postgres'
import { UUIDT } from '../../../src/utils/utils'
import { EventPipelineRunner } from '../../../src/worker/ingestion/event-pipeline/runner'
import { createOrganization, createTeam, POSTGRES_DELETE_TABLES_QUERY } from '../../helpers/sql'

describe('workerTasks.runEventPipeline()', () => {
    let hub: Hub
    let redis: Redis.Redis
    let closeHub: () => Promise<void>
    const OLD_ENV = process.env

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub()
        redis = await hub.redisPool.acquire()
        await hub.postgres.query(PostgresUse.COMMON_WRITE, POSTGRES_DELETE_TABLES_QUERY, undefined, '') // Need to clear the DB to avoid unique constraint violations on ids
        process.env = { ...OLD_ENV } // Make a copy
    })

    afterAll(async () => {
        await hub.redisPool.release(redis)
        await closeHub()
        process.env = OLD_ENV // Restore old environment
    })

    beforeEach(() => {
        // Use fake timers to ensure that we don't need to wait on e.g. retry logic.
        jest.useFakeTimers({ advanceTimers: 30 })
    })

    afterEach(() => {
        jest.clearAllTimers()
        jest.useRealTimers()
        jest.clearAllMocks()
    })

    test('throws DependencyUnavailableError on postgres errors', async () => {
        const errorMessage =
            'connection to server at "posthog-pgbouncer" (171.20.65.128), port 6543 failed: server closed the connection unexpectedly'
        const organizationId = await createOrganization(hub.postgres)
        const teamId = await createTeam(hub.postgres, organizationId)

        const pgQueryMock = jest.spyOn(Pool.prototype, 'query').mockImplementation(() => {
            return Promise.reject(new Error(errorMessage))
        })

        const event = {
            distinct_id: 'asdf',
            ip: '',
            team_id: teamId,
            event: 'some event',
            properties: {},
            site_url: 'https://example.com',
            now: new Date().toISOString(),
            uuid: new UUIDT().toString(),
        }
        await expect(new EventPipelineRunner(hub, event).runEventPipeline(event)).rejects.toEqual(
            new DependencyUnavailableError(errorMessage, 'Postgres', new Error(errorMessage))
        )
        pgQueryMock.mockRestore()
    })
})
