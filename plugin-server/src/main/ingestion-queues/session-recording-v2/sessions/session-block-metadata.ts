export interface SessionBlockMetadata {
    /** Unique identifier for the session */
    sessionId: string
    /** ID of the team that owns this session recording */
    teamId: number
    /** Byte offset where this session block starts in the batch file */
    blockStartOffset: number
    /** Length of this session block in bytes */
    blockLength: number
    /** Timestamp of the first event in the session block */
    startTimestamp: number
    /** Timestamp of the last event in the session block */
    endTimestamp: number
}
