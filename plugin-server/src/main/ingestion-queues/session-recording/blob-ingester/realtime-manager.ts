import { Redis } from 'ioredis'

import { RedisPool } from '../../../../types'
import { timeoutGuard } from '../../../../utils/db/utils'
import { status } from '../../../../utils/status'
import { IncomingRecordingMessage } from './types'
import { convertToPersistedMessage } from './utils'

const SESSION_TTL_SECONDS = 60 * 60 // 1 hour

/**
 * RealtimeManager
 *
 * This class is responsible for realtime access and optimising the session managers via commiting interim offsets to redis
 */
export class RealtimeManager {
    constructor(private redisPool: RedisPool) {
        // TODO:
        // 1. Start up subscription to key for handling realtime updates
        // 2. Shut down listener on stop
        // 3. Add way to clean up old sessions
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

    private getSnapshotsKey(teamId: number, suffix: string): string {
        return `@posthog/replay/snapshots/team-${teamId}/${suffix}`
    }

    public async addMessage(message: IncomingRecordingMessage): Promise<void> {
        const key = this.getSnapshotsKey(message.team_id, message.session_id)

        try {
            await this.run(`addMessage ${key} `, async (client) => {
                const pipeline = client.pipeline()
                pipeline.zadd(key, message.metadata.timestamp, JSON.stringify(convertToPersistedMessage(message)))
                pipeline.expire(key, SESSION_TTL_SECONDS)
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
        const key = this.getSnapshotsKey(teamId, sessionId)

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
        const key = this.getSnapshotsKey(teamId, sessionId)

        try {
            await this.run(`clearAllMessages ${key} `, async (client) => {
                return client.del(key)
            })
        } catch (error) {
            status.error('🧨', 'RealtimeManager failed to clear all messages from redis', {
                error,
                key,
            })
        }
    }
}
