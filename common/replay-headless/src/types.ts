export interface ViewportEvent {
    timestamp: number
    width: number
    height: number
}

export interface SnapshotBlock {
    key: string
    start: number
    end: number
}

export interface PlayerConfig {
    blocks: SnapshotBlock[]
    recordingApiBaseUrl: string
    recordingApiSecret: string
    teamId: number
    sessionId: string
    playbackSpeed: number
    skipInactivity?: boolean
    startTimestamp?: number
    endTimestamp?: number
    mouseTail?: boolean
    viewportEvents?: ViewportEvent[]
}

export interface InactivityPeriod {
    ts_from_s: number
    ts_to_s: number | null
    active: boolean
}
