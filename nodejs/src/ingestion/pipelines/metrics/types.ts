import { Message } from 'node-rdkafka'

import { KafkaDebugContext } from '~/ingestion/framework/helpers'

export type MetricsIngestionMessage = {
    token: string
    teamId: number
    message: Message
    bytesUncompressed: number
    /** Sum of per-point sizes from the `bytes_uncompressed_records` header. 0 for batches from older producers. */
    bytesUncompressedRecords: number
    bytesCompressed: number
    recordCount: number
}

export type MetricsPipelineInput = { message: Message }

export type MetricsMessageContext = { message: Message; debugContext?: KafkaDebugContext }
