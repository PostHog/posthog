import { Redis } from 'ioredis'

import { RedisPool } from '../../../../types'
import { timeoutGuard } from '../../../../utils/db/utils'
import { status } from '../../../../utils/status'
import { IncomingRecordingMessage } from './types'
import { convertToPersistedMessage } from './utils'

/**
 * RealtimeManager
 *
 * This class is responsible for realtime access and optimising the session managers via commiting interim offsets to redis
 */
export class RealtimeManager {
    constructor(private redisPool: RedisPool) {}

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
        try {
            await this.run(`addMessage ${message.team_id} ${message.session_id} `, async (client) => {
                return client.zadd(
                    this.getSnapshotsKey(message.team_id, message.session_id),
                    message.metadata.timestamp,
                    JSON.stringify(convertToPersistedMessage(message))
                )
            })
            status.info('📡', 'RealtimeManager added recording message to redis')
        } catch (error) {
            status.error('🧨', 'RealtimeManager failed to add recording message to redis', {
                error,
                sessionId: message.session_id,
            })
        }
    }
}
