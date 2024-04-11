// This is the incoming message from Kafka

import { RRWebEvent } from '../../../types'

export type RawHeatmapEvent = {
    /**
     * session id lets us offer example recordings on high traffic parts of the page,
     * and could let us offer more advanced filtering of heatmap data
     * we will break the relationship between particular sessions and clicks in aggregating this data
     * it should always be treated as an exemplar and not as concrete values
     */
    $session_id: string
    $viewport_width: number
    $viewport_height: number
    $pointer_target_fixed: boolean
}

export type HeatmapEvent = RawHeatmapEvent & {
    // x is the x with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    x: number
    // y is the y with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    y: number
    scale_factor: 16 // in the future we may support other values
    timestamp: string
}

export type IncomingHeatmapEventMessage = RawHeatmapEvent & {
    metadata: {
        topic: string
        partition: number
        timestamp: number
    }
    team_id: number
    $pointer_x: number
    $pointer_y: number
}

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
}

export type PersistedRecordingMessage = {
    window_id?: string
    data: any
}
