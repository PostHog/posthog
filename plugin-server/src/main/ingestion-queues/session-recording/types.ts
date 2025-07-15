// This is the incoming message from Kafka

import { RRWebEvent } from '../../../types'

export type IncomingRecordingMessage = {
    metadata: {
        topic: string
        partition: number
        rawSize: number
        lowOffset: number
        highOffset: number
        timestamp: number
        consoleLogIngestionEnabled?: boolean
    }

    team_id: number
    distinct_id: string
    session_id: string
    eventsByWindowId: Record<string, RRWebEvent[]>
    eventsRange: {
        start: number
        end: number
    }
    snapshot_source: string | null
    snapshot_library: string | null
}

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

export type ParsedBatch = {
    sessions: IncomingRecordingMessage[]
    partitionStats: BatchStats[]
}
