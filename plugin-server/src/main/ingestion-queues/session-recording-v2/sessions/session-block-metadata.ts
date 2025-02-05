export interface SessionBlockMetadata {
    /** Unique identifier for the session */
    sessionId: string
    /** ID of the team that owns this session recording */
    teamId: number
    /** Length of this session block in bytes */
    blockLength: number
    /** Timestamp of the first event in the session block */
    startTimestamp: number
    /** Timestamp of the last event in the session block */
    endTimestamp: number
    /** URL to the block data with byte range query parameter, if available */
    blockUrl: string | null
}
