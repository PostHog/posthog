import { Message } from 'node-rdkafka'

import { KafkaDebugContext } from '~/ingestion/framework/helpers'

export type MetricsIngestionMessage = {
    token: string
    teamId: number
    message: Message
    bytesUncompressed: number
    bytesCompressed: number
    recordCount: number
}

export type MetricsPipelineInput = { message: Message }

export type MetricsMessageContext = { message: Message; debugContext?: KafkaDebugContext }
