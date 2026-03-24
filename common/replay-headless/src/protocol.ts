/**
 * Shared protocol between the headless replay player (HostBridge) and
 * the rasterizer host (PlayerController).
 *
 * The player runs inside a Puppeteer-controlled browser and communicates
 * with the rasterizer via:
 *   - A window global for config (rasterizer → player, injected before page load)
 *   - A DOM event to start playback (rasterizer → player)
 *   - An exposed function callback (player → rasterizer)
 *
 * This module defines the types, event names, and Window augmentation
 * so both sides are compile-time checked against the same contract.
 */

// --- Types ---

export interface ViewportEvent {
    timestamp: number
    width: number
    height: number
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
    showMetadataFooter?: boolean
    viewportEvents?: ViewportEvent[]
}

export interface PlayerError {
    code: string
    message: string
    retryable: boolean
}

export interface InactivityPeriod {
    ts_from_s: number
    ts_to_s: number | null
    active: boolean
}

// --- Player → rasterizer messages ---

export type PlayerMessage =
    | { type: 'loading_progress'; loaded: number; total: number }
    | { type: 'started' }
    | { type: 'ended' }
    | { type: 'error'; code: string; message: string; retryable: boolean }
    | { type: 'inactivity_periods'; periods: InactivityPeriod[] }

export const PLAYER_EMIT_FN = '__posthog_player_emit__'
export const PLAYER_CONFIG_KEY = '__posthog_player_config__'

// --- Event names (rasterizer → player) ---

export const PLAYER_START_EVENT = 'posthog-player-start'

// --- Window augmentation ---

declare global {
    interface Window {
        // Config injected by rasterizer via evaluateOnNewDocument before page load
        [PLAYER_CONFIG_KEY]?: PlayerConfig
        // Player → rasterizer callback (installed by page.exposeFunction)
        [PLAYER_EMIT_FN]?: (msg: PlayerMessage) => Promise<void>
    }
}
