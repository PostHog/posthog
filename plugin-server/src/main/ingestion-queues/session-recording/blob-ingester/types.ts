export type KafkaTopic = string
// | 'recording_events'
// | 'recording_events_retry_1'
// | 'recording_events_retry_2'
// | 'recording_events_retry_3'

export type RecordingEventGroup = {
    id: string
    teamId: number
    sessionId: string
    distinctId: string // OK if this distinct ID changes through the recording, we just need to store a single distinct ID
    events: RecordingEvent[]
    size: number
    oldestEventTimestamp: number
    oldestOffsets: Record<string, number> // Key is '{topic}-{partition}'
    newestOffsets: Record<string, number> // Key is '{topic}-{partition}'
    oldestOriginalOffset: number // The original offset of the oldest message in the event group. Used for ordering
    timer?: NodeJS.Timeout
    status?: 'sending' | 'active'
}

export type RecordingEvent = {
    eventId: string
    messages: RecordingMessage[]
    complete: boolean
    timestamp: number
    eventType: number
    eventSource: number
    windowId: string
    sessionId: string
    distinctId: string
    teamId: number
    kafkaTopic: KafkaTopic
    kafkaPartition: number
    oldestOffset: number
    oldestOriginalOffset: number // The original offset of the oldest message in the event. Used for ordering
    newestOffset: number
}

export type RecordingMessage = {
    eventId: string
    value: string
    timestamp: number
    eventType: number
    eventSource: number
    windowId: string
    sessionId: string
    distinctId: string
    chunkCount: number
    chunkIndex: number
    teamId: number
    kafkaTopic: KafkaTopic
    kafkaPartition: number
    kafkaOffset: number
    originalKafkaOffset: number // If this message was re-sent on a retry topic, this is the original Kafka offset. Used for ordering
    kafkaKey: string
}

export type OffsetMetadata = {
    topic: KafkaTopic
    partition: number
    offset: number
}

// This is the incoming message from Kafka
export type IncomingRecordingMessage = {
    metadata: OffsetMetadata

    team_id: number
    distinct_id: string
    session_id: string
    window_id?: string

    // Properties data
    chunk_id: string
    chunk_index: number
    chunk_count: number
    data: string
    compresssion: string
    has_full_snapshot: boolean
    events_summary: {
        timestamp: number
        type: number
        data: any
    }[]
}

// This is the incoming message from Kafka
export type PersistedRecordingMessage = {
    window_id?: string
    data: any
}
