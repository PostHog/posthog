import { eventWithTime } from '@posthog/rrweb-types'

import { findNewEvents } from '../sessionRecordingPlayerLogic'

/**
 * Determines which new events to add to the rrweb replayer.
 *
 * Legacy path (index-based): assumes sources load sequentially so new events
 * are always appended after existing ones. Simple and fast.
 *
 * Store path (timestamp-based): sources may load out of order (e.g. seek to
 * minute 30, then load minute 5). New events can appear before, between, or
 * after existing events. Uses timestamp-count matching to find the diff.
 */
export function selectNewEvents(
    allSnapshots: eventWithTime[],
    currentEvents: eventWithTime[],
    useStoreBasedLoading: boolean
): eventWithTime[] {
    if (useStoreBasedLoading) {
        return findNewEvents(allSnapshots, currentEvents)
    }
    return allSnapshots.slice(currentEvents.length)
}

const POSITION_UPDATE_INTERVAL_MS = 5000

/**
 * Determines whether the playback position should be reported to the
 * LoadingScheduler so it can slide its buffer window forward.
 */
export function shouldUpdatePlaybackPosition(newTimestamp: number, lastUpdateTimestamp: number | undefined): boolean {
    return !lastUpdateTimestamp || newTimestamp - lastUpdateTimestamp > POSITION_UPDATE_INTERVAL_MS
}
