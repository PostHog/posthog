export interface ProtoKafkaHeader {
    key: string
    value: Buffer
}

export interface ProtoKafkaMessage {
    topic: string
    partition: number
    offset: number | Long
    timestamp?: number | Long
    key?: Buffer
    value?: Buffer
    headers: ProtoKafkaHeader[]
}

export interface IngestBatchRequest {
    messages: ProtoKafkaMessage[]
}

export interface IngestBatchResponse {
    status: number // 0 = OK, 1 = ERROR
    accepted: number
    error: string
}

interface Long {
    toNumber(): number
}
