const POSITION_UPDATE_INTERVAL_MS = 5000

/**
 * Determines whether the playback position should be reported to the
 * load planner so it can slide its buffer window forward.
 */
export function shouldUpdatePlaybackPosition(newTimestamp: number, lastUpdateTimestamp: number | undefined): boolean {
    return !lastUpdateTimestamp || newTimestamp - lastUpdateTimestamp > POSITION_UPDATE_INTERVAL_MS
}
