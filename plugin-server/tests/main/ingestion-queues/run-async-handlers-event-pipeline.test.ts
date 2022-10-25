import { RetryError } from '@posthog/plugin-scaffold'
import Redis from 'ioredis'
import { KafkaJSError } from 'kafkajs'

import { Hub } from '../../../src/types'
import { DependencyError } from '../../../src/utils/db/error'
import { createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import { setupPlugins } from '../../../src/worker/plugins/setup'
import { workerTasks } from '../../../src/worker/tasks'
import {
    createOrganization,
    createPlugin,
    createPluginConfig,
    createTeam,
    POSTGRES_DELETE_TABLES_QUERY,
} from '../../helpers/sql'

describe('workerTasks.runAsyncHandlersEventPipeline()', () => {
    // Tests the failure cases for the workerTasks.runAsyncHandlersEventPipeline
    // task. Note that this equally applies to e.g. runEventPipeline task as
    // well and likely could do with adding additional tests for that.

    let hub: Hub
    let redis: Redis.Redis
    let closeHub: () => Promise<void>

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub()
        redis = await hub.redisPool.acquire()
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
        jest.runOnlyPendingTimers()
        jest.useRealTimers()
        jest.clearAllMocks()
    })

    test('throws on produce errors', async () => {
        // To ensure that producer errors are retried and not swallowed, we need
        // to ensure that these are bubbled up to the main consumer loop. Note
        // that the `KafkaJSError` is translated to a generic `DependencyError`.
        // This is to allow the specific decision of whether the error is
        // retryable to happen as close to the dependency as possible.
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
            return Promise.reject(new KafkaJSError('Failed to produce', { retriable: true }))
        })

        await expect(
            workerTasks.runAsyncHandlersEventPipeline(hub, {
                event: {
                    distinctId: 'asdf',
                    ip: '',
                    teamId: teamId,
                    event: 'some event',
                    properties: {},
                    eventUuid: new UUIDT().toString(),
                },
            })
        ).rejects.toEqual(new DependencyError('Failed to produce', true))
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

        await expect(workerTasks.runAsyncHandlersEventPipeline(hub, { event })).resolves.toEqual({
            args: [expect.objectContaining(event), { distinctId: 'asdf', loaded: false, teamId }],
            lastStep: 'runAsyncHandlersStep',
        })

        // Ensure the retry call is made.
        jest.runOnlyPendingTimers()

        expect(hub.kafkaProducer.producer.send).toHaveBeenCalledTimes(2)
    })

    test(`doesn't throw on arbitrary failures`, async () => {
        // If we receive a `RetryError`, we should retry the task within the
        // pipeline rather than throwing it to the main consumer loop.
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

        await expect(workerTasks.runAsyncHandlersEventPipeline(hub, { event })).resolves.toEqual({
            args: [expect.objectContaining(event), { distinctId: 'asdf', loaded: false, teamId }],
            lastStep: 'runAsyncHandlersStep',
        })
    })
})
