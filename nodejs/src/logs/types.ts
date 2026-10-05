import { Message } from 'node-rdkafka'

export type LogsIngestionMessage = {
    token: string
    teamId: number
    message: Message
    bytesUncompressed: number
    /** Sum of per-record content sizes from the `bytes_uncompressed_records` header; 0 for batches from older producers. */
    bytesUncompressedRecords: number
    bytesCompressed: number
    recordCount: number
    /** Earliest row timestamp in epoch microseconds, from the `min_timestamp` header; absent from older producers. */
    minTimestampMicros?: number
}
