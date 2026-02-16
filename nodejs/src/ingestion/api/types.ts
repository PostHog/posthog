export interface SerializedKafkaMessage {
    topic: string
    partition: number
    offset: number
    timestamp?: number
    key: string | null // base64-encoded
    value: string | null // base64-encoded
    headers: Array<Record<string, string>> // header values are base64-encoded
}

export interface IngestBatchRequest {
    messages: SerializedKafkaMessage[]
}

export interface IngestBatchResponse {
    status: 'ok' | 'error'
    accepted?: number
    error?: string
}
