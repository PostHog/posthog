import { DateTime } from 'luxon'
import { MessageHeader } from 'node-rdkafka'

import { RRWebEvent } from '../../../../types'

export interface ParsedMessageData {
    distinct_id: string
    session_id: string
    eventsByWindowId: { [key: string]: RRWebEvent[] }
    eventsRange: {
        start: DateTime
        end: DateTime
    }
    snapshot_source: string | null
    snapshot_library: string | null
    headers?: MessageHeader[]
    metadata: {
        partition: number
        topic: string
        rawSize: number
        offset: number
        timestamp: number
    }
}
