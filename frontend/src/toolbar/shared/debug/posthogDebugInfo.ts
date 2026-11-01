/** The parts of posthog-js that the toolbar's debug info reads. Any posthog-js version on a page fits it. */
export interface DebugInfoPosthog {
    version?: string
    config?: { api_host?: string; ui_host?: string | null; rageclick?: unknown }
    autocapture?: { isEnabled?: boolean }
    deadClicksAutocapture?: { lazyLoadedDeadClicksAutocapture?: unknown }
    heatmaps?: { isEnabled?: boolean }
    sessionRecording?: { started?: boolean; status?: string }
    get_session_replay_url?: () => string
}

export interface PosthogDebugInfo {
    version: string | null
    apiHost: string | null
    uiHost: string | null
    autocapture: boolean
    rageclicks: boolean
    deadClicks: boolean
    heatmaps: boolean
    sessionRecordingStarted: boolean
    sessionRecordingStatus: string | null
    sessionReplayUrl: string | null
}

/** A page can replace any of these with a getter that throws, so each read stands alone. */
function read<T>(get: () => T | null | undefined): T | null {
    try {
        return get() ?? null
    } catch {
        return null
    }
}

export function readPosthogDebugInfo(posthog: DebugInfoPosthog | null): PosthogDebugInfo {
    const autocapture = !!read(() => posthog?.autocapture?.isEnabled)
    return {
        version: read(() => posthog?.version),
        apiHost: read(() => posthog?.config?.api_host),
        uiHost: read(() => posthog?.config?.ui_host),
        autocapture,
        rageclicks: autocapture && !!read(() => posthog?.config?.rageclick),
        deadClicks: !!read(() => posthog?.deadClicksAutocapture?.lazyLoadedDeadClicksAutocapture),
        heatmaps: !!read(() => posthog?.heatmaps?.isEnabled),
        sessionRecordingStarted: !!read(() => posthog?.sessionRecording?.started),
        sessionRecordingStatus: read(() => posthog?.sessionRecording?.status),
        sessionReplayUrl: read(() => posthog?.get_session_replay_url?.()),
    }
}
