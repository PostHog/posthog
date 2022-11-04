// While these test cases focus on runAsyncHandlersEventPipeline, they were
// explicitly intended to test that failures to produce to the `jobs` topic
// due to availability errors would be bubbled up to the consumer, where we can
// then make decisions about how to handle this case e.g. here we test that it
// simply would bubble up to the KafkaJS consumer runnner where it can handle
// retries.
//
// There is complicating factor in that the pipeline uses a separate Node Worker
// to run the pipeline, which means we can't easily mock the `produce` call, and
// as such the test is broken into answering these questions separately, with no
// integration test between the two:
//
//  1. using the Piscina task runner to run the pipeline results in the
//     DependencyUnavailableError Error being thrown.
//  2. the KafkaQueue consumer handler will let the error bubble up to the
//     KafkaJS consumer runner, which we assume will handle retries.
import { RetryError } from '@posthog/plugin-scaffold'
import Redis from 'ioredis'
import { KafkaJSError } from 'kafkajs'

import { KAFKA_EVENTS_JSON } from '../../../src/config/kafka-topics'
import { Hub } from '../../../src/types'
import { DependencyUnavailableError } from '../../../src/utils/db/error'
import { createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import { setupPlugins } from '../../../src/worker/plugins/setup'
import { createTaskRunner } from '../../../src/worker/worker'
import {
    createOrganization,
    createPlugin,
    createPluginConfig,
    createTeam,
    POSTGRES_DELETE_TABLES_QUERY,
} from '../../helpers/sql'
import { IngestionConsumer } from './../../../src/main/ingestion-queues/kafka-queue'

describe('workerTasks.runAsyncHandlersEventPipeline()', () => {
    // Tests the failure cases for the workerTasks.runAsyncHandlersEventPipeline
    // task. Note that this equally applies to e.g. runEventPipeline task as
    // well and likely could do with adding additional tests for that.
    //
    // We are assuming here that we are bubbling up any errors thrown from the
    // Piscina task runner to the consumer here, I couldn't figure out a nice
    // way to mock things in subprocesses to test this however.

    let hub: Hub
    let redis: Redis.Redis
    let closeHub: () => Promise<void>
    let piscinaTaskRunner: ({ task, args }) => Promise<any>

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub()
        redis = await hub.redisPool.acquire()
        piscinaTaskRunner = createTaskRunner(hub)
        await hub.postgres.query(POSTGRES_DELETE_TABLES_QUERY) // Need to clear the DB to avoid unique constraint violations on ids
    })

    afterAll(async () => {
        await hub.redisPool.release(redis)
        await closeHub()
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

        jest.spyOn(hub.kafkaProducer.producer, 'send').mockImplementationOnce(() => {
            return Promise.reject(new KafkaJSError('Failed to produce'))
        })

        await expect(
            piscinaTaskRunner({
                task: 'runAsyncHandlersEventPipeline',
                args: {
                    event: {
                        distinctId: 'asdf',
                        ip: '',
                        teamId: teamId,
                        event: 'some event',
                        properties: {},
                        eventUuid: new UUIDT().toString(),
                    },
                },
            })
        ).rejects.toEqual(
            new DependencyUnavailableError('Failed to produce', 'Kafka', new KafkaJSError('Failed to produce'))
        )
    })

    test('retry on RetryError', async () => {
        // If we receive a `RetryError`, we should retry the task within the
        // pipeline rather than throwing it to the main consumer loop.
        // Note that we assume the retries are happening async as is the
        // currently functionality, i.e. outside of the consumer loop, but we
        // should arguably move this to a separate retry topic.
        const organizationId = await createOrganization(hub.postgres)
        const plugin = await createPlugin(hub.postgres, {
            organization_id: organizationId,
            name: 'runEveryMinute plugin',
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

        // This isn't strictly correct in terms of where this is being raised
        // from i.e. `producer.send` doesn't ever raise a `RetryError`, but
        // it was just convenient to do so and is hopefully close enough to
        // reality.
        // NOTE: we only mock once such that the second call will succeed
        jest.spyOn(hub.kafkaProducer.producer, 'send').mockImplementationOnce(() => {
            return Promise.reject(new RetryError('retry error'))
        })

        const event = {
            distinctId: 'asdf',
            ip: '',
            teamId: teamId,
            event: 'some event',
            properties: {},
            eventUuid: new UUIDT().toString(),
        }

        await expect(
            piscinaTaskRunner({
                task: 'runAsyncHandlersEventPipeline',
                args: { event },
            })
        ).resolves.toEqual({
            args: [expect.objectContaining(event), { distinctId: 'asdf', loaded: false, teamId }],
            lastStep: 'runAsyncHandlersStep',
        })

        // Ensure the retry call is made.
        jest.runOnlyPendingTimers()

        expect(hub.kafkaProducer.producer.send).toHaveBeenCalledTimes(2)
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
            ip: '',
            teamId: teamId,
            event: 'some event',
            properties: {},
            eventUuid: new UUIDT().toString(),
        }

        await expect(
            piscinaTaskRunner({
                task: 'runAsyncHandlersEventPipeline',
                args: { event },
            })
        ).resolves.toEqual({
            args: [expect.objectContaining(event), { distinctId: 'asdf', loaded: false, teamId }],
            lastStep: 'runAsyncHandlersStep',
        })
    })
})

describe('eachBatchAsyncHandlers', () => {
    // We want to ensure that if the handler rejects, then the consumer will
    // raise to the consumer, triggering the KafkaJS retry logic. Here we are
    // assuming that piscina will reject the returned promise, which according
    // to https://github.com/piscinajs/piscina#method-runtask-options should be
    // the case.
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
    })

    afterEach(async () => {
        await closeHub?.()
    })

    test('rejections from piscina are bubbled up to the consumer', async () => {
        const ingestionConsumer = new IngestionConsumer(hub, {
            runAsyncHandlersEventPipeline: () => {
                throw new DependencyUnavailableError(
                    'Failed to produce',
                    'Kafka',
                    new KafkaJSError('Failed to produce')
                )
            },
            runEventPipeline: () => {
                throw new DependencyUnavailableError(
                    'Failed to produce',
                    'Kafka',
                    new KafkaJSError('Failed to produce')
                )
            },
        })

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
        ).rejects.toEqual(
            new DependencyUnavailableError('Failed to produce', 'Kafka', new KafkaJSError('Failed to produce'))
        )
    })
})
