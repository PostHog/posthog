// This is the incoming message from Kafka

import { RRWebEvent } from '../../../types'

export type HeatmapEvent = {
    /**
     * session id lets us offer example recordings on high traffic parts of the page,
     * and could let us offer more advanced filtering of heatmap data
     * we will break the relationship between particular sessions and clicks in aggregating this data
     * it should always be treated as an exemplar and not as concrete values
     */
    session_id: string
    screen_width: number
    screen_height: number
    // the original X value, we are likely to throw this away in any aggregation
    x: number
    // the original Y value, we are likely to throw this away in any aggregation
    y: number
    // quadrant x is the x with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    quadrant_x: number
    // quadrant y is the y with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    quadrant_y: number
    resolution: 16 // in the future we may support other values
    timestamp: string // is it?
}

export type IncomingHeatmapEventMessage = {
    metadata: {
        topic: string
        partition: number
        timestamp: number
    }

    team_id: number
    // ??
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
