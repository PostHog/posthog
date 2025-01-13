// This is the incoming message from Kafka

export type PersistedRecordingMessage = {
    window_id?: string
    data: any
}

export type BatchStats = {
    /**
     * Subset of the kafka Message class, used to report metrics only
     */
    readonly partition: number
    readonly offset: number
    readonly timestamp?: number
}
