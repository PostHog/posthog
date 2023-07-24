// This is the incoming message from Kafka

import { TopicPartitionOffset } from 'node-rdkafka-acosom'

import { RRWebEvent } from '../../../types'

export type IncomingRecordingMessage = {
    metadata: TopicPartitionOffset & {
        timestamp: number
    }

    team_id: number
    distinct_id: string
    session_id: string
    window_id?: string
    events: RRWebEvent[]
    // NOTE: This is only for migrating from one consumer to the other
    replayIngestionConsumer: 'v1' | 'v2'
}

// This is the incoming message from Kafka
export type PersistedRecordingMessage = {
    window_id?: string
    data: any
}
