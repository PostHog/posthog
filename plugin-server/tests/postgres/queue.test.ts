import Piscina from '@posthog/piscina'

import { CeleryQueue } from '../../src/main/ingestion-queues/celery-queue'
import { ingestEvent } from '../../src/main/ingestion-queues/ingest-event'
import { KafkaQueue } from '../../src/main/ingestion-queues/kafka-queue'
import { startQueues } from '../../src/main/ingestion-queues/queue'
import { Hub, LogLevel } from '../../src/types'
import { Client } from '../../src/utils/celery/client'
import { createHub } from '../../src/utils/db/hub'
import { delay } from '../../src/utils/utils'

jest.setTimeout(60000) // 60 sec timeout
jest.mock('../../src/main/ingestion-queues/kafka-queue')
jest.mock('../../src/utils/status')
jest.mock('../../src/main/ingestion-queues/ingest-event')

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
        KAFKA_ENABLED: false,
    })

    const redis = await hub.redisPool.acquire()
    await redis.del(hub.PLUGINS_CELERY_QUEUE)
    await redis.del(hub.CELERY_DEFAULT_QUEUE)
    await hub.redisPool.release(redis)
    return [hub, closeHub]
}

describe('queue', () => {
    test('process event queue', async () => {
        const [hub, closeHub] = await createTestHub()
        const redis = await hub.redisPool.acquire()

        // Nothing in the redis queue
        const queue1 = await redis.llen(hub.PLUGINS_CELERY_QUEUE)
        expect(queue1).toBe(0)

        const kwargs = {
            distinct_id: 'hedgehog',
            ip: null,
            site_url: 'hedgehogs.com',
            data: { pineapple: 1 },
            team_id: 1234,
            now: 'now',
            sent_at: 'later',
        }
        const args = Object.values(kwargs)

        const client = new Client(hub.db, hub.PLUGINS_CELERY_QUEUE)
        for (let i = 0; i < 6; i++) {
            client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})
        }

        await delay(1000)

        expect(await redis.llen(hub.PLUGINS_CELERY_QUEUE)).toBe(6)
        const fakePiscina = { run: jest.fn() } as any
        const queue = (await startQueues(hub, fakePiscina, {})).ingestion
        await advanceOneTick()

        await delay(1000)

        expect(await redis.llen(hub.PLUGINS_CELERY_QUEUE)).not.toBe(6)

        await queue!.pause()

        expect(ingestEvent).toHaveBeenCalledTimes(6)
        const { data, ...expected_args } = kwargs
        expect(ingestEvent).toHaveBeenLastCalledWith(
            expect.anything(),
            expect.anything(),
            expect.objectContaining({ ...expected_args, ...data, uuid: expect.anything() }),
            expect.anything()
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
            })
            piscina = { run: jest.fn() } as any
        })

        afterEach(async () => {
            await closeHub()
        })

        it('starts ingestion queue by default', async () => {
            const queues = await startQueues(hub, piscina)

            expect(queues).toEqual({
                ingestion: expect.any(KafkaQueue),
                auxiliary: null,
            })
        })

        it('handles ingestion being turned off', async () => {
            hub.capabilities.ingestion = false

            const queues = await startQueues(hub, piscina)

            expect(queues).toEqual({
                ingestion: null,
                auxiliary: null,
            })
        })
    })
})
