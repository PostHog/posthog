import { Writable } from 'stream'

/**
 * Represents a stream and its completion handler for writing a batch of session recordings
 */
export interface StreamWithFinish {
    /** A writable stream that accepts a serialized batch of session recordings */
    stream: Writable
    /**
     * Completes the writing process for the entire batch
     * Should be called after all session recordings in the batch have been written to the stream
     * For example, this might finalize an S3 multipart upload or close a file
     */
    finish: () => Promise<void>
}

/**
 * Interface for writing session batch files to a storage backend
 *
 * Writers are agnostic to the session batch format - they simply write a stream of bytes
 * to a destination (e.g. S3, disk). The internal structure of session batches (blocks,
 * compression, etc.) is handled by the upstream components.
 */
export interface SessionBatchFileWriter {
    /**
     * Creates a new batch write operation
     * Returns a writable stream for the raw bytes and a finish method to complete the write
     *
     * Example usage:
     * ```
     * const { stream, finish } = writer.newBatch()
     * stream.write(batchBytes) // Writer doesn't interpret these bytes
     * await finish() // Completes the write operation
     * ```
     */
    newBatch(): StreamWithFinish
}
