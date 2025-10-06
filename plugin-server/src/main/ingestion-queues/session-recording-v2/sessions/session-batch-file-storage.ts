import { TeamId } from '../../../../types'

export interface WriteSessionData {
    /** The serialized session block data */
    buffer: Buffer

    sessionId: string

    teamId: TeamId
}

export interface WriteSessionResult {
    /** Number of bytes written */
    bytesWritten: number
    /** URL to access this session block, if available */
    url: string | null
    /** Retention period, in days, for this block, if available */
    retentionPeriodDays: number | null
}

/**
 * Represents a writer for a batch of session recordings
 */
export interface SessionBatchFileWriter {
    /**
     * Writes a session block to the batch
     * Handles backpressure from the underlying stream
     *
     * @param data - The session data to write
     * @returns Promise that resolves with the number of bytes written and URL for the block
     * @throws If there is an error writing the data
     */
    writeSession(data: WriteSessionData): Promise<WriteSessionResult>

    /**
     * Completes the writing process for the entire batch
     * Should be called after all session recordings in the batch have been written
     * For example, this might finalize an S3 multipart upload or close a file
     */
    finish(): Promise<void>
}

/**
 * Interface for storing session batch files in a storage backend
 *
 * Storage implementations are agnostic to the session batch format - they simply write bytes
 * to a destination (e.g. S3, disk). The internal structure of session batches (blocks,
 * compression, etc.) is handled by the upstream components.
 */
export interface SessionBatchFileStorage {
    /**
     * Creates a new batch write operation
     * Returns a writer for the batch that handles writing individual sessions
     *
     * Example usage:
     * ```
     * const writer = storage.newBatch()
     * const result = await writer.writeSession(sessionBytes)
     * await writer.finish() // Completes the write operation
     * ```
     */
    newBatch(): SessionBatchFileWriter

    /**
     * Checks the health of the storage backend
     * Returns true if the storage backend is healthy, false otherwise
     */
    checkHealth(): Promise<boolean>
}
