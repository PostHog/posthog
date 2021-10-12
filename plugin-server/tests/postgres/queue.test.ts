import { setupPiscina } from '../../benchmarks/postgres/helpers/piscina'
import { startQueues } from '../../src/main/ingestion-queues/queue'
import { Hub, LogLevel } from '../../src/types'
import { Client } from '../../src/utils/celery/client'
import { createHub } from '../../src/utils/db/hub'
import { delay } from '../../src/utils/utils'
import { runProcessEvent } from '../../src/worker/plugins/run'

jest.setTimeout(60000) // 60 sec timeout

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

test('pause and resume queue', async () => {
    const [hub, closeHub] = await createTestHub()
    const redis = await hub.redisPool.acquire()
    // Nothing in the redis queue
    const queue1 = await redis.llen(hub.PLUGINS_CELERY_QUEUE)
    expect(queue1).toBe(0)

    const kwargs = {
        distinct_id: 'my-id',
        ip: '127.0.0.1',
        site_url: 'http://localhost',
        data: {
            event: '$pageview',
            properties: {},
        },
        team_id: 2,
        now: new Date().toISOString(),
        sent_at: new Date().toISOString(),
    }
    const args = Object.values(kwargs)

    // Tricky: make a client to the PLUGINS_CELERY_QUEUE queue (not CELERY_DEFAULT_QUEUE as normally)
    // This is so that the worker can directly read from it. Basically we will simulate a event sent from posthog.
    const client = new Client(hub.db, hub.PLUGINS_CELERY_QUEUE)
    for (let i = 0; i < 6; i++) {
        client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})
    }

    await delay(1000)

    // There'll be a "tick lag" with the events moving from one queue to the next. :this_is_fine:
    expect(await redis.llen(hub.PLUGINS_CELERY_QUEUE)).toBe(6)
    const piscina = setupPiscina(2, 2)
    const queue = (
        await startQueues(hub, piscina, {
            processEvent: (event) => runProcessEvent(hub, event),
            ingestEvent: () => Promise.resolve({ success: true }),
        })
    ).ingestion
    await advanceOneTick()

    expect(await redis.llen(hub.PLUGINS_CELERY_QUEUE)).not.toBe(6)

    await queue.pause()

    const pluginQueue = await redis.llen(hub.PLUGINS_CELERY_QUEUE)

    expect(pluginQueue).toBeGreaterThan(0)

    await delay(100)

    expect(await redis.llen(hub.PLUGINS_CELERY_QUEUE)).toBe(pluginQueue)

    await delay(100)

    expect(await redis.llen(hub.PLUGINS_CELERY_QUEUE)).toBe(pluginQueue)

    await queue.resume()

    await delay(500)

    expect(await redis.llen(hub.PLUGINS_CELERY_QUEUE)).toBe(0)

    await queue.stop()
    await hub.redisPool.release(redis)
    await closeHub()
    await piscina.destroy()
})

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

    await queue.pause()

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

    await queue.stop()
    await hub.redisPool.release(redis)
    await closeHub()
})
