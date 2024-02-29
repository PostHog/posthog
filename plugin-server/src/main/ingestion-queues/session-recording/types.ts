// This is the incoming message from Kafka

import { TopicPartitionOffset } from 'node-rdkafka'

import { RRWebEvent } from '../../../types'

export type IncomingRecordingMessage = {
    metadata: TopicPartitionOffset & {
        timestamp: number
        consoleLogIngestionEnabled?: boolean
    }

    team_id: number
    distinct_id: string
    session_id: string
    window_id?: string
    events: RRWebEvent[]
    snapshot_source: string | null
}

// This is the incoming message from Kafka
export type PersistedRecordingMessage = {
    window_id?: string
    data: any
}
