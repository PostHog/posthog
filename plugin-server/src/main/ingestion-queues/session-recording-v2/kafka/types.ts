import { RRWebEvent } from '../../../../types'

export interface ParsedMessageData {
    distinct_id: string
    session_id: string
    eventsByWindowId: { [key: string]: RRWebEvent[] }
    eventsRange: { start: number; end: number }
    snapshot_source?: string
    metadata: {
        partition: number
        topic: string
        rawSize: number
        offset: number
        timestamp: number
    }
}
