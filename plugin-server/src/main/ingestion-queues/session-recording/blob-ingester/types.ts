export type KafkaTopic = string
// | 'recording_events'
// | 'recording_events_retry_1'
// | 'recording_events_retry_2'
// | 'recording_events_retry_3'

// This is the incoming message from Kafka
export type IncomingRecordingMessage = {
    metadata: {
        topic: KafkaTopic
        partition: number
        offset: number
    }

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
