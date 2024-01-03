import { captureException } from '@sentry/node'
import { randomUUID } from 'crypto'
import { Redis } from 'ioredis'
import { EventEmitter } from 'node:events'

import { PluginsServerConfig, RedisPool } from '../../../../types'
import { timeoutGuard } from '../../../../utils/db/utils'
import { status } from '../../../../utils/status'
import { createRedis } from '../../../../utils/utils'
import { IncomingRecordingMessage } from '../types'
import { convertToPersistedMessage } from '../utils'

const Keys = {
    snapshots(prefix: string, teamId: number, suffix: string): string {
        return `${prefix}snapshots/team-${teamId}/${suffix}`
    },
    realtimeSubscriptions: (prefix: string): string => `${prefix}realtime-subscriptions`,
}

/**
 * RealtimeManager
 *
 * This class is responsible for realtime access and optimising the session managers via committing interim offsets to redis
 */
export class RealtimeManager extends EventEmitter {
    private pubsubRedis: Redis | undefined
    private ttlSeconds: number

    constructor(private redisPool: RedisPool, private serverConfig: PluginsServerConfig) {
        super()

        // We TTL for double than the buffer age seconds to allow for
        // things like redploys or persistance timing
        this.ttlSeconds = this.serverConfig.SESSION_RECORDING_MAX_BUFFER_AGE_SECONDS * 5
    }

    private emitSubscriptionEvent(teamId: number, sessionId: string): void {
        this.emit(`subscription::${teamId}::${sessionId}`)
    }

    public onSubscriptionEvent(teamId: number, sessionId: string, cb: () => void): () => void {
        this.on(`subscription::${teamId}::${sessionId}`, cb)

        return () => {
            this.off(`subscription::${teamId}::${sessionId}`, cb)
        }
    }

    public async subscribe(): Promise<void> {
        this.pubsubRedis = await createRedis(this.serverConfig)
        await this.pubsubRedis.subscribe(Keys.realtimeSubscriptions(this.serverConfig.SESSION_RECORDING_REDIS_PREFIX))

        this.pubsubRedis.on('message', (channel, message) => {
            try {
                const subMessage = JSON.parse(message) as { team_id: number; session_id: string }
                this.emitSubscriptionEvent(subMessage.team_id, subMessage.session_id)
            } catch (e) {
                captureException('Failed to parse message from redis pubsub', e)
            }
        })
    }

    public async unsubscribe(): Promise<void> {
        await this.pubsubRedis?.unsubscribe(
            Keys.realtimeSubscriptions(this.serverConfig.SESSION_RECORDING_REDIS_PREFIX)
        )

        this.pubsubRedis?.disconnect()
        this.pubsubRedis = undefined
    }

    private async run<T>(description: string, fn: (client: Redis) => Promise<T>): Promise<T | null> {
        const client = await this.redisPool.acquire()
        const timeout = timeoutGuard(`${description} delayed. Waiting over 30 seconds.`)
        try {
            return await fn(client)
        } catch (error) {
            if (error instanceof SyntaxError) {
                // invalid JSON
                return null
            } else {
                throw error
            }
        } finally {
            clearTimeout(timeout)
            await this.redisPool.release(client)
        }
    }

    public async addMessage(message: IncomingRecordingMessage): Promise<void> {
        const key = Keys.snapshots(
            this.serverConfig.SESSION_RECORDING_REDIS_PREFIX,
            message.team_id,
            message.session_id
        )

        try {
            await this.run(`addMessage ${key} `, async (client) => {
                const pipeline = client.pipeline()
                pipeline.zadd(key, message.metadata.timestamp, JSON.stringify(convertToPersistedMessage(message)))
                pipeline.expire(key, this.ttlSeconds)
                return pipeline.exec()
            })
        } catch (error) {
            status.error('🧨', 'RealtimeManager failed to add recording message to redis', {
                error,
                key,
            })
        }
    }

    public async addMessagesFromBuffer(
        teamId: number,
        sesssionId: string,
        messages: string,
        timestamp: number
    ): Promise<void> {
        const key = Keys.snapshots(this.serverConfig.SESSION_RECORDING_REDIS_PREFIX, teamId, sesssionId)

        try {
            await this.run(`addMessage ${key} `, async (client) => {
                const pipeline = client.pipeline()
                pipeline.zadd(key, timestamp, messages)
                pipeline.expire(key, this.ttlSeconds)
                return pipeline.exec()
            })
        } catch (error) {
            status.error('🧨', 'RealtimeManager failed to add recording message to redis', {
                error,
                key,
            })
        }
    }

    public async clearMessages(teamId: number, sessionId: string, timestamp: number): Promise<void> {
        const key = Keys.snapshots(this.serverConfig.SESSION_RECORDING_REDIS_PREFIX, teamId, sessionId)

        try {
            await this.run(`clearMessages ${key} `, async (client) => {
                return client.zremrangebyscore(key, 0, timestamp)
            })
        } catch (error) {
            status.error('🧨', 'RealtimeManager failed to clear message from redis', {
                error,
                key,
            })
        }
    }

    public async clearAllMessages(teamId: number, sessionId: string): Promise<void> {
        const key = Keys.snapshots(this.serverConfig.SESSION_RECORDING_REDIS_PREFIX, teamId, sessionId)

        try {
            await this.run(`clearAllMessages ${key} `, async (client) => {
                /**
                 * We could delete the key here but (https://redis.io/commands/del/) del is O(M)
                 * where M is the number of items in the sorted set, for a large buffer this could be
                 * a lot of work.
                 *
                 * Whereas RENAME (https://redis.io/commands/rename/) is O(1)
                 * (_almost_ always O(1))
                 * """
                 *  If newkey already exists it is overwritten, when this happens RENAME executes an implicit DEL operation,
                 *  so if the deleted key contains a very big value it may cause high latency
                 *  even if RENAME itself is usually a constant-time operation.
                 *  """
                 *  So, we rename the key to expired-<key>-<uuid>, so that it can't possibly clash
                 *  and let it expire
                 */
                const pipeline = client.pipeline()
                const newKey = `expired-${key}-${randomUUID()}`
                pipeline.rename(`${key}`, newKey)
                // renaming shouldn't affect the existing TTL
                // but, we set one anyway to be sure
                pipeline.expire(newKey, 1)
                return pipeline.exec()
            })
        } catch (error) {
            captureException(error, { tags: { teamId, sessionId }, extra: { key } })
            status.error('🧨', 'RealtimeManager failed to clear all messages from redis', {
                error,
                key,
            })
        }
    }
}
