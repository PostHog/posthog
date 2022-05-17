import Piscina from '@posthog/piscina'

import { setupPiscina } from '../../benchmarks/postgres/helpers/piscina'
import { CeleryQueue } from '../../src/main/ingestion-queues/celery-queue'
import { KafkaQueue } from '../../src/main/ingestion-queues/kafka-queue'
import { startQueues } from '../../src/main/ingestion-queues/queue'
import { Hub, LogLevel } from '../../src/types'
import { Client } from '../../src/utils/celery/client'
import { createHub } from '../../src/utils/db/hub'
import { delay } from '../../src/utils/utils'
import { runProcessEvent } from '../../src/worker/plugins/run'

jest.setTimeout(60000) // 60 sec timeout
jest.mock('../../src/main/ingestion-queues/kafka-queue')
jest.mock('../../src/utils/status')

function advanceOneTick() {
    return new Promise((resolve) => process.nextTick(resolve))
}

async function createTestHub(): Promise<[Hub, () => Promise<void>]> {
    const [hub, closeHub] = await createHub({
        REDIS_POOL_MIN_SIZE: 3,
        REDIS_POOL_MAX_SIZE: 3,
        PLUGINS_CELERY_QUEUE: 'ttt-test-plugins-celery-queue',
        CELERY_DEFAULT_QUEUE: 'ttt-test-celery-default-queue',
        LOG_LEVEL: LogLevel.Log,
    })

    const redis = await hub.redisPool.acquire()
    await redis.del(hub.PLUGINS_CELERY_QUEUE)
    await redis.del(hub.CELERY_DEFAULT_QUEUE)
    await hub.redisPool.release(redis)
    return [hub, closeHub]
}

describe('queue', () => {
    test('plugin jobs queue', async () => {
        const [hub, closeHub] = await createTestHub()
        const redis = await hub.redisPool.acquire()

        // Nothing in the redis queue
        const queue1 = await redis.llen(hub.PLUGINS_CELERY_QUEUE)
        expect(queue1).toBe(0)

        const kwargs = {
            pluginConfigTeam: 2,
            pluginConfigId: 39,
            type: 'someJobName',
            jobOp: 'start',
            payload: { a: 1 },
        }
        const args = Object.values(kwargs)

        const client = new Client(hub.db, hub.PLUGINS_CELERY_QUEUE)
        for (let i = 0; i < 6; i++) {
            client.sendTask('posthog.tasks.plugins.plugin_job', args, {})
        }

        await delay(1000)

        expect(await redis.llen(hub.PLUGINS_CELERY_QUEUE)).toBe(6)
        const fakePiscina = { run: jest.fn() } as any
        const queue = (await startQueues(hub, fakePiscina, {})).ingestion
        await advanceOneTick()

        await delay(1000)

        expect(await redis.llen(hub.PLUGINS_CELERY_QUEUE)).not.toBe(6)

        await queue!.pause()

        expect(fakePiscina.run).toHaveBeenCalledWith(
            expect.objectContaining({
                task: 'enqueueJob',
                args: {
                    job: {
                        pluginConfigTeam: 2,
                        pluginConfigId: 39,
                        type: 'someJobName',
                        payload: { a: 1, $operation: 'start' },
                        timestamp: expect.any(Number),
                    },
                },
            })
        )

        await queue!.stop()
        await hub.redisPool.release(redis)
        await closeHub()
    })

    describe('capabilities', () => {
        let hub: Hub
        let piscina: Piscina
        let closeHub: () => Promise<void>

        beforeEach(async () => {
            ;[hub, closeHub] = await createHub({
                LOG_LEVEL: LogLevel.Warn,
                KAFKA_ENABLED: true,
            })
            piscina = { run: jest.fn() } as any
        })

        afterEach(async () => {
            await closeHub()
        })

        it('starts ingestion and auxilary queues by default', async () => {
            const queues = await startQueues(hub, piscina)

            expect(queues).toEqual({
                ingestion: expect.any(KafkaQueue),
                auxiliary: expect.any(CeleryQueue),
            })
        })

        it('handles ingestion being turned off', async () => {
            hub.capabilities.ingestion = false

            const queues = await startQueues(hub, piscina)

            expect(queues).toEqual({
                ingestion: null,
                auxiliary: expect.any(CeleryQueue),
            })
        })

        it('handles job processing being turned off', async () => {
            hub.capabilities.processJobs = false

            const queues = await startQueues(hub, piscina)

            expect(queues).toEqual({
                ingestion: expect.any(KafkaQueue),
                auxiliary: null,
            })
        })
    })
})
