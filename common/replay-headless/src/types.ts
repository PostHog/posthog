export interface ViewportEvent {
    timestamp: number
    width: number
    height: number
}

export interface RecordingBlock {
    key: string
    start_byte: number
    end_byte: number
    start_timestamp: string
    end_timestamp: string
}

export interface PlayerConfig {
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
