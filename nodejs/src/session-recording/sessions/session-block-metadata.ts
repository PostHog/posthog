import { DateTime } from 'luxon'

export interface SessionBlockMetadata {
    /** Unique identifier for the session */
    sessionId: string
    /** ID of the team that owns this session recording */
    teamId: number
    /** Distinct ID of the session recording */
    distinctId: string
    /** ID of the batch this session block belongs to */
    batchId: string
    /** Length of this session block in bytes */
    blockLength: number
    /** Timestamp of the first event in the session block */
    startDateTime: DateTime
    /** Timestamp of the last event in the session block */
    endDateTime: DateTime
    /** URL to the block data with byte range query parameter, if available */
    blockUrl: string | null
    /** First URL in the session */
    firstUrl: string | null
    /** All URLs visited in the session */
    urls: string[]
    /** Number of events in the session */
    eventCount: number
    /** Number of click events in the session */
    clickCount: number
    /** Number of keypress events in the session */
    keypressCount: number
    /** Number of mouse activity events in the session */
    mouseActivityCount: number
    /** Number of milliseconds the user was active */
    activeMilliseconds: number
    /** Number of console.log events in the session */
    consoleLogCount: number
    /** Number of console.warn events in the session */
    consoleWarnCount: number
    /** Number of console.error events in the session */
    consoleErrorCount: number
    /** Size of the session data in bytes */
    size: number
    /** Number of messages in the session */
    messageCount: number
    /** Source of the snapshot */
    snapshotSource: string | null
    /** Library used for the snapshot */
    snapshotLibrary: string | null
    /** Retention period for this session block */
    retentionPeriodDays: number | null
}
