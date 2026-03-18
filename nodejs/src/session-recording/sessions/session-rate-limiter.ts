import { ParsedMessageData } from '../kafka/types'
import { SessionBatchMetrics } from './metrics'

/**
 * Rate limiter for session recordings
 * Tracks event count per session and enforces a maximum events per batch limit
 */
export class SessionRateLimiter {
    private readonly eventCounts = new Map<string, number>()
    private readonly limitedSessions = new Set<string>()
    private readonly sessionPartitions = new Map<string, number>()

    constructor(private readonly maxEventsPerSession: number = Number.MAX_SAFE_INTEGER) {}

    /**
     * Handle a message for a session
     * @param sessionKey - Unique session identifier (e.g., "teamId$sessionId")
     * @param partition - Partition number for this message
     * @param message - The message containing events
     * @returns true if message should be processed, false if rate limited
     */
    public handleMessage(sessionKey: string, partition: number, message: ParsedMessageData): boolean {
        // Count total events in the message across all windows
        let eventCount = 0
        for (const events of Object.values(message.eventsByWindowId)) {
            eventCount += events.length
        }

        const currentCount = this.eventCounts.get(sessionKey) ?? 0
        const newCount = currentCount + eventCount

        // Always increment the count and track partition
        this.eventCounts.set(sessionKey, newCount)
        this.sessionPartitions.set(sessionKey, partition)

        if (this.limitedSessions.has(sessionKey)) {
            SessionBatchMetrics.incrementEventsRateLimited()
            return false
        }

        if (newCount > this.maxEventsPerSession) {
            this.limitedSessions.add(sessionKey)
            SessionBatchMetrics.incrementSessionsRateLimited()
            SessionBatchMetrics.incrementEventsRateLimited()
            return false
        }

        return true
    }

    /**
     * Get current event count for a session
     */
    public getEventCount(sessionKey: string): number {
        return this.eventCounts.get(sessionKey) ?? 0
    }

    /**
     * Remove tracking for a session (used when partition is discarded)
     */
    public removeSession(sessionKey: string): void {
        this.eventCounts.delete(sessionKey)
        this.limitedSessions.delete(sessionKey)
        this.sessionPartitions.delete(sessionKey)
    }

    /**
     * Discard all sessions for a given partition
     */
    public discardPartition(partition: number): void {
        const sessionsToRemove: string[] = []

        for (const [sessionKey, sessionPartition] of this.sessionPartitions.entries()) {
            if (sessionPartition === partition) {
                sessionsToRemove.push(sessionKey)
            }
        }

        for (const sessionKey of sessionsToRemove) {
            this.removeSession(sessionKey)
        }
    }

    /**
     * Clear all rate limiting state
     */
    public clear(): void {
        this.eventCounts.clear()
        this.limitedSessions.clear()
        this.sessionPartitions.clear()
    }
}
