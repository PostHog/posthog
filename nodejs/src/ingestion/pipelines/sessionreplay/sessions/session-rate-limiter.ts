import { SessionBatchMetrics } from './metrics'

/**
 * Rate limiter for session recordings
 * Tracks event count per session and enforces a maximum events per batch limit
 */
export class SessionRateLimiter {
    private readonly eventCounts = new Map<string, number>()
    private readonly limitedSessions = new Set<string>()

    constructor(private readonly maxEventsPerSession: number = Number.MAX_SAFE_INTEGER) {}

    private static key(teamId: number, sessionId: string): string {
        return `${teamId}$${sessionId}`
    }

    /**
     * Handle a message's events for a session
     * @returns true if the message should be processed, false if rate limited
     */
    public handleMessage(teamId: number, sessionId: string, eventCount: number): boolean {
        const key = SessionRateLimiter.key(teamId, sessionId)

        const newCount = (this.eventCounts.get(key) ?? 0) + eventCount
        this.eventCounts.set(key, newCount)

        if (this.limitedSessions.has(key)) {
            SessionBatchMetrics.incrementEventsRateLimited()
            return false
        }

        if (newCount > this.maxEventsPerSession) {
            this.limitedSessions.add(key)
            SessionBatchMetrics.incrementSessionsRateLimited()
            SessionBatchMetrics.incrementEventsRateLimited()
            return false
        }

        return true
    }

    /**
     * Get current event count for a session
     */
    public getEventCount(teamId: number, sessionId: string): number {
        return this.eventCounts.get(SessionRateLimiter.key(teamId, sessionId)) ?? 0
    }

    /**
     * Clear all rate limiting state
     */
    public clear(): void {
        this.eventCounts.clear()
        this.limitedSessions.clear()
    }
}
