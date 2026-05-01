import { LiveEvent } from '~/types'

export const FILTERED_LIVE_USER_WINDOW_SECONDS = 60

export const pruneRecentUsersByLastSeen = (
    recentUsersByLastSeen: Map<string, number>,
    nowTs: number,
    windowSeconds: number = FILTERED_LIVE_USER_WINDOW_SECONDS
): Map<string, number> => {
    const threshold = nowTs - windowSeconds
    let nextRecentUsersByLastSeen: Map<string, number> | null = null

    for (const [distinctId, lastSeenTs] of recentUsersByLastSeen) {
        if (lastSeenTs > threshold) {
            continue
        }

        nextRecentUsersByLastSeen = nextRecentUsersByLastSeen ?? new Map(recentUsersByLastSeen)
        nextRecentUsersByLastSeen.delete(distinctId)
    }

    return nextRecentUsersByLastSeen ?? recentUsersByLastSeen
}

export const upsertRecentUsersByLastSeenFromEvents = (
    recentUsersByLastSeen: Map<string, number>,
    events: LiveEvent[],
    newerThan: Date
): Map<string, number> => {
    const newerThanTs = newerThan.getTime() / 1000
    let nextRecentUsersByLastSeen = recentUsersByLastSeen

    for (const event of events) {
        const eventTs = new Date(event.timestamp).getTime() / 1000
        if (eventTs <= newerThanTs) {
            continue
        }

        const distinctId = event.distinct_id
        if (!distinctId) {
            continue
        }

        if ((nextRecentUsersByLastSeen.get(distinctId) ?? 0) >= eventTs) {
            continue
        }

        if (nextRecentUsersByLastSeen === recentUsersByLastSeen) {
            nextRecentUsersByLastSeen = new Map(recentUsersByLastSeen)
        }

        nextRecentUsersByLastSeen.set(distinctId, eventTs)
    }

    return nextRecentUsersByLastSeen
}
