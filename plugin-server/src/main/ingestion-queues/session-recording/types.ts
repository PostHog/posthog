// This is the incoming message from Kafka

import { RRWebEvent } from '../../../types'

export type IncomingRecordingMessage = {
    metadata: {
        topic: string
        partition: number
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
}

export type PersistedRecordingMessage = {
    window_id?: string
    data: any
}
