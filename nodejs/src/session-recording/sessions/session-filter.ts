import { logger } from '../../utils/logger'
import { Limiter } from '../../utils/token-bucket'
import { MessageWithTeam } from '../teams/types'
import { SessionBatchMetrics } from './metrics'
import { SessionTracker } from './session-tracker'

export class SessionFilter {
    constructor(
        private readonly sessionTracker: SessionTracker,
        private readonly sessionLimiter: Limiter
    ) {}

    public async filterBatch(messages: MessageWithTeam[]): Promise<MessageWithTeam[]> {
        // First pass: identify which sessions are rate limited
        const rateLimitedSessions = new Set<string>()

        for (const message of messages) {
            const { teamId } = message.team
            const { session_id: sessionId } = message.message
            const sessionKey = `${teamId}:${sessionId}`

            // Skip if we already know this session is rate limited
            if (rateLimitedSessions.has(sessionKey)) {
                continue
            }

            const isNewSession = await this.sessionTracker.trackSession(teamId, sessionId)

            if (isNewSession) {
                const isAllowed = this.sessionLimiter.consume(String(teamId), 1)
                if (!isAllowed) {
                    rateLimitedSessions.add(sessionKey)
                    SessionBatchMetrics.incrementNewSessionsRateLimited()
                    logger.debug('🔁', 'session_filter_new_session_rate_limited', {
                        partition: message.message.metadata.partition,
                        sessionId,
                        teamId,
                    })
                }
            }
        }

        // Second pass: filter out all messages belonging to rate limited sessions
        return messages.filter((message) => {
            const sessionKey = `${message.team.teamId}:${message.message.session_id}`
            return !rateLimitedSessions.has(sessionKey)
        })
    }
}
