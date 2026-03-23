export type { ViewportEvent, PlayerConfig, PlayerError, InactivityPeriod } from './protocol'

export interface RecordingBlock {
    key: string
    start_byte: number
    end_byte: number
    start_timestamp: string
    end_timestamp: string
}
