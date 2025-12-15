import Redis from 'ioredis'
import { Pool } from 'pg'

import { BatchWritingPersonsStore } from '~/worker/ingestion/persons/batch-writing-person-store'

import { Hub } from '../../../src/types'
import { DependencyUnavailableError } from '../../../src/utils/db/error'
import { closeHub, createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import { EventPipelineRunner } from '../../../src/worker/ingestion/event-pipeline/runner'
import { BatchWritingGroupStoreForBatch } from '../../../src/worker/ingestion/groups/batch-writing-group-store'
import { PostgresPersonRepository } from '../../../src/worker/ingestion/persons/repositories/postgres-person-repository'
import { createOrganization, createTeam, getTeam, resetTestDatabase } from '../../helpers/sql'

describe('workerTasks.runEventPipeline()', () => {
    let hub: Hub
    let personRepository: PostgresPersonRepository
    let redis: Redis.Redis
    const OLD_ENV = process.env

    beforeAll(async () => {
        hub = await createHub()
        personRepository = new PostgresPersonRepository(hub.db.postgres)
        redis = await hub.redisPool.acquire()
        await resetTestDatabase()
        process.env = { ...OLD_ENV } // Make a copy
    })

    afterAll(async () => {
        await hub.redisPool.release(redis)
        await closeHub(hub)
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
        const team = (await getTeam(hub, teamId))!

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
        const personsStore = new BatchWritingPersonsStore(personRepository, hub.kafkaProducer)
        const groupStoreForBatch = new BatchWritingGroupStoreForBatch(
            hub.db,
            hub.groupRepository,
            hub.clickhouseGroupRepository
        )
        await expect(
            new EventPipelineRunner(
                {
                    SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: hub.SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP,
                    TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE: hub.TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE,
                    PIPELINE_STEP_STALLED_LOG_TIMEOUT: hub.PIPELINE_STEP_STALLED_LOG_TIMEOUT,
                    PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: hub.PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT,
                    PERSON_MERGE_ASYNC_ENABLED: hub.PERSON_MERGE_ASYNC_ENABLED,
                    PERSON_MERGE_ASYNC_TOPIC: hub.PERSON_MERGE_ASYNC_TOPIC,
                    PERSON_MERGE_SYNC_BATCH_SIZE: hub.PERSON_MERGE_SYNC_BATCH_SIZE,
                    PERSON_JSONB_SIZE_ESTIMATE_ENABLE: hub.PERSON_JSONB_SIZE_ESTIMATE_ENABLE,
                    PERSON_PROPERTIES_UPDATE_ALL: hub.PERSON_PROPERTIES_UPDATE_ALL,
                },
                hub.kafkaProducer,
                hub.teamManager,
                hub.groupTypeManager,
                event,
                null,
                personsStore,
                groupStoreForBatch
            ).runEventPipeline(event, team)
        ).rejects.toEqual(new DependencyUnavailableError(errorMessage, 'Postgres', new Error(errorMessage)))
        pgQueryMock.mockRestore()
    })
})
