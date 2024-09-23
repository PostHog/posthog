// While these test cases focus on runAppsOnEventPipeline, they were
// explicitly intended to test that failures to produce to the `jobs` topic
// due to availability errors would be bubbled up to the consumer, where we can
// then make decisions about how to handle this case e.g. here we test that it
// simply would bubble up to the KafkaJS consumer runnner where it can handle
// retries.
//

import Redis from 'ioredis'
import LibrdKafkaError from 'node-rdkafka/lib/error'

import { KAFKA_EVENTS_JSON } from '../../../src/config/kafka-topics'
import { buildOnEventIngestionConsumer } from '../../../src/main/ingestion-queues/on-event-handler-consumer'
import { Hub, ISOTimestamp } from '../../../src/types'
import { DependencyUnavailableError } from '../../../src/utils/db/error'
import { closeHub, createHub } from '../../../src/utils/db/hub'
import { PostgresUse } from '../../../src/utils/db/postgres'
import { UUIDT } from '../../../src/utils/utils'
import { processOnEventStep } from '../../../src/worker/ingestion/event-pipeline/runAsyncHandlersStep'
import { setupPlugins } from '../../../src/worker/plugins/setup'
import { teardownPlugins } from '../../../src/worker/plugins/teardown'
import {
    createOrganization,
    createPlugin,
    createPluginConfig,
    createTeam,
    POSTGRES_DELETE_TABLES_QUERY,
} from '../../helpers/sql'

jest.setTimeout(10000)

describe('runAppsOnEventPipeline()', () => {
    // Tests the failure cases for the workerTasks.runAppsOnEventPipeline
    // task. Note that this equally applies to e.g. runEventPipeline task as
    // well and likely could do with adding additional tests for that.

    let hub: Hub
    let redis: Redis.Redis

    beforeEach(async () => {
        // Use fake timers to ensure that we don't need to wait on e.g. retry logic.
        jest.useFakeTimers({ advanceTimers: true })
        hub = await createHub()
        redis = await hub.redisPool.acquire()
        await hub.postgres.query(PostgresUse.COMMON_WRITE, POSTGRES_DELETE_TABLES_QUERY, null, 'deleteTables') // Need to clear the DB to avoid unique constraint violations on ids
    })

    afterEach(async () => {
        await hub.redisPool.release(redis)
        await teardownPlugins(hub)
        await closeHub(hub)
        jest.clearAllTimers()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    test('throws on produce errors', async () => {
        // To ensure that producer errors are retried and not swallowed, we need
        // to ensure that these are bubbled up to the main consumer loop. Note
        // that the `KafkaJSError` is translated to a generic `DependencyUnavailableError`.
        // This is to allow the specific decision of whether the error is
        // retriable to happen as close to the dependency as possible.
        const organizationId = await createOrganization(hub.postgres)
        const plugin = await createPlugin(hub.postgres, {
            organization_id: organizationId,
            name: 'fails to produce',
            plugin_type: 'source',
            is_global: false,
            source__index_ts: `
                export async function onEvent(event, { jobs }) {
                    await jobs.test().runNow()
                }

                export const jobs = {
                    test: async () => {}
                }
            `,
        })

        const teamId = await createTeam(hub.postgres, organizationId)
        await createPluginConfig(hub.postgres, { team_id: teamId, plugin_id: plugin.id })
        await setupPlugins(hub)

        const error = new LibrdKafkaError({
            name: 'Failed to produce',
            message: 'Failed to produce',
            code: 1,
            errno: 1,
            origin: 'test',
            isRetriable: true,
        })

        jest.spyOn(hub.kafkaProducer.producer, 'produce').mockImplementation(
            (topic, partition, message, key, timestamp, headers, cb) => cb(error)
        )

        await expect(
            processOnEventStep(hub, {
                distinctId: 'asdf',
                teamId: teamId,
                event: 'some event',
                properties: {},
                eventUuid: new UUIDT().toString(),
                person_created_at: null,
                person_properties: {},
                timestamp: new Date().toISOString() as ISOTimestamp,
                elementsList: [],
            })
        ).rejects.toEqual(new DependencyUnavailableError('Failed to produce', 'Kafka', error))
    })

    test(`doesn't throw on arbitrary failures`, async () => {
        // If we receive an arbitrary error, we should just skip the event. We
        // only want to retry on `RetryError` and `DependencyUnavailableError` as these are
        // things under our control.
        const organizationId = await createOrganization(hub.postgres)
        const plugin = await createPlugin(hub.postgres, {
            organization_id: organizationId,
            name: 'runEveryMinute plugin',
            plugin_type: 'source',
            is_global: false,
            source__index_ts: `
                export async function onEvent(event, { jobs }) {
                    throw new Error('arbitrary failure')
                }
            `,
        })

        const teamId = await createTeam(hub.postgres, organizationId)
        await createPluginConfig(hub.postgres, { team_id: teamId, plugin_id: plugin.id })
        await setupPlugins(hub)

        const event = {
            distinctId: 'asdf',
            teamId: teamId,
            event: 'some event',
            properties: {},
            eventUuid: new UUIDT().toString(),
            person_created_at: null,
            person_properties: {},
            timestamp: new Date().toISOString() as ISOTimestamp,
            elementsList: [],
        }

        await expect(processOnEventStep(hub, event)).resolves.toEqual(null)
    })
})

describe('eachBatchAsyncHandlers', () => {
    let hub: Hub

    beforeEach(async () => {
        jest.useFakeTimers({ advanceTimers: true })
        hub = await createHub()
    })

    afterEach(async () => {
        await closeHub(hub)
        jest.useRealTimers()
    })

    test('rejections from kafka are bubbled up to the consumer', async () => {
        const ingestionConsumer = buildOnEventIngestionConsumer({ hub })
        const error = new LibrdKafkaError({ message: 'test', code: 1, errno: 1, origin: 'test', isRetriable: true })

        jest.spyOn(ingestionConsumer, 'eachBatch').mockRejectedValue(
            new DependencyUnavailableError('Failed to produce', 'Kafka', error)
        )

        await expect(
            ingestionConsumer.eachBatchConsumer({
                batch: {
                    topic: KAFKA_EVENTS_JSON,
                    partition: 0,
                    highWatermark: '0',
                    messages: [
                        {
                            key: Buffer.from('key'),
                            value: Buffer.from(
                                JSON.stringify({
                                    distinctId: 'asdf',
                                    ip: '',
                                    teamId: 1,
                                    event: 'some event',
                                    properties: JSON.stringify({}),
                                    eventUuid: new UUIDT().toString(),
                                    timestamp: '0',
                                })
                            ),
                            timestamp: '0',
                            offset: '0',
                            size: 0,
                            attributes: 0,
                        },
                    ],
                    isEmpty: jest.fn(),
                    firstOffset: jest.fn(),
                    lastOffset: jest.fn(),
                    offsetLag: jest.fn(),
                    offsetLagLow: jest.fn(),
                },
                resolveOffset: jest.fn(),
                heartbeat: jest.fn(),
                isRunning: () => true,
                isStale: () => false,
                commitOffsetsIfNecessary: jest.fn(),
                uncommittedOffsets: jest.fn(),
                pause: jest.fn(),
            })
        ).rejects.toEqual(new DependencyUnavailableError('Failed to produce', 'Kafka', error))
    })
})
