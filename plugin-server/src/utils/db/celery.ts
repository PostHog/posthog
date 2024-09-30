import { CacheOptions } from '@posthog/plugin-scaffold'
import { createPool, Pool as GenericPool } from 'generic-pool'
import Redis from 'ioredis'

import { CELERY_DEFAULT_QUEUE } from '../../config/constants'
import { PluginsServerConfig } from '../../types'
import { instrumentQuery } from '../metrics'
import { createRedisClient, UUIDT } from '../utils'
import { timeoutGuard } from './utils'

/**
 * NOTE: We sometimes need to trigger flows in the main posthog app from the plugin server.
 * This has been done by celery and continues to do so. At some point we should consider an alternative
 * such as a shared message bus or an internal HTTP API.
 */
export class CeleryHelper {
    private redisPool: GenericPool<Redis.Redis>

    constructor(config: PluginsServerConfig) {
        // NOTE: We define a redis pool explicitly using the POSTHOG_REDIS_HOST as celery
        // only works if it is talking to the same redis instance as the django "posthog" app
        this.redisPool = createPool<Redis.Redis>(
            {
                create: async () => {
                    return await createRedisClient(config.POSTHOG_REDIS_HOST, {
                        port: config.POSTHOG_REDIS_PORT,
                        password: config.POSTHOG_REDIS_PASSWORD,
                    })
                },
                destroy: async (client) => {
                    await client.quit()
                },
            },
            {
                min: config.REDIS_POOL_MIN_SIZE,
                max: config.REDIS_POOL_MAX_SIZE,
                autostart: true,
            }
        )
    }

    private redisLPush(key: string, value: unknown, options: CacheOptions = {}): Promise<number> {
        const { jsonSerialize = true } = options

        return instrumentQuery('query.redisLPush', undefined, async () => {
            const client = await this.redisPool.acquire()
            const timeout = timeoutGuard('LPushing redis key delayed. Waiting over 30 sec to lpush key', { key })
            try {
                const serializedValue = jsonSerialize ? JSON.stringify(value) : (value as string | string[])
                return await client.lpush(key, serializedValue)
            } finally {
                clearTimeout(timeout)
                await this.redisPool.release(client)
            }
        })
    }

    /** Calls Celery task. Works similarly to Task.apply_async in Python. */
    async applyAsync(taskName: string, args: any[] = [], kwargs: Record<string, any> = {}): Promise<void> {
        const taskId = new UUIDT().toString()
        const deliveryTag = new UUIDT().toString()
        const body = [args, kwargs, { callbacks: null, errbacks: null, chain: null, chord: null }]
        /** A base64-encoded JSON representation of the body tuple. */
        const bodySerialized = Buffer.from(JSON.stringify(body)).toString('base64')
        await this.redisLPush(CELERY_DEFAULT_QUEUE, {
            body: bodySerialized,
            'content-encoding': 'utf-8',
            'content-type': 'application/json',
            headers: {
                lang: 'js',
                task: taskName,
                id: taskId,
                retries: 0,
                root_id: taskId,
                parent_id: null,
                group: null,
            },
            properties: {
                correlation_id: taskId,
                delivery_mode: 2,
                delivery_tag: deliveryTag,
                delivery_info: { exchange: '', routing_key: CELERY_DEFAULT_QUEUE },
                priority: 0,
                body_encoding: 'base64',
            },
        })
    }
}
