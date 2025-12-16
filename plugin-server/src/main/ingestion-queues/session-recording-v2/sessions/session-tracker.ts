import { RedisPool } from '../../../../types'
import { logger } from '../../../../utils/logger'
import { SessionBatchMetrics } from './metrics'

export type NewSessionCallback = (teamId: number, sessionId: string) => Promise<void>

export class SessionTracker {
    private readonly keyPrefix = '@posthog/replay/session-seen'
    private readonly ttlSeconds = 48 * 60 * 60 // 48 hours

    constructor(private readonly redisPool: RedisPool) {}

    private static readonly noopCallback: NewSessionCallback = () => Promise.resolve()

    /**
     * Check if session has been seen before, mark as seen if not.
     * Invokes the callback for new sessions.
     *
     * @param teamId - The team ID
     * @param sessionId - The session ID
     * @param onNewSession - Callback invoked when a new session is detected
     */
    public async trackSession(
        teamId: number,
        sessionId: string,
        onNewSession: NewSessionCallback = SessionTracker.noopCallback
    ): Promise<void> {
        const key = this.generateKey(teamId, sessionId)
        const client = await this.redisPool.acquire()

        try {
            // Use SET with NX (only set if not exists) and EX (expiry) for atomic check-and-set
            // Returns 'OK' if key was set (new session), null if already exists
            const wasSet = await client.set(key, '1', 'EX', this.ttlSeconds, 'NX')
            const isNewSession = wasSet === 'OK'

            if (isNewSession) {
                SessionBatchMetrics.incrementNewSessionsDetected()

                logger.debug('session_tracker_new_session', {
                    teamId,
                    sessionId,
                })

                await onNewSession(teamId, sessionId)
            }
        } finally {
            await this.redisPool.release(client)
        }
    }

    private generateKey(teamId: number, sessionId: string): string {
        return `${this.keyPrefix}:${teamId}:${sessionId}`
    }
}
