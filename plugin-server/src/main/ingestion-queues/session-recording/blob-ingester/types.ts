// This is the incoming message from Kafka

export type RRWebEvent = Record<string, any> & {
    timestamp: number
    type: number
    data: any
}

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
    events: RRWebEvent[]
}

// This is the incoming message from Kafka
export type PersistedRecordingMessage = {
    window_id?: string
    data: any
}
