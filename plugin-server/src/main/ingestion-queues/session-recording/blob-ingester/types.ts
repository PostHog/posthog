// This is the incoming message from Kafka
export type IncomingRecordingMessage = {
    metadata: {
        topic: string
        partition: number
        offset: number
        timestamp: number
    }

    team_id: number
    distinct_id: string
    session_id: string
    window_id?: string

    // Properties data
    data: string
    compression: string
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
