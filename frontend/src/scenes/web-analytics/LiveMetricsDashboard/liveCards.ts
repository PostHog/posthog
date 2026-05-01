export type LiveStatCardId = 'users_online' | 'unique_visitors' | 'pageviews'

export type LiveContentCardId =
    | 'active_users_chart'
    | 'top_paths'
    | 'top_referrers'
    | 'devices'
    | 'browsers'
    | 'top_countries'
    | 'bot_events_chart'
    | 'bot_traffic'
    | 'countries'
    | 'live_events'

export const DEFAULT_STAT_ORDER: readonly LiveStatCardId[] = ['users_online', 'unique_visitors', 'pageviews']

export const DEFAULT_CONTENT_ORDER: readonly LiveContentCardId[] = [
    'active_users_chart',
    'top_paths',
    'top_referrers',
    'devices',
    'browsers',
    'top_countries',
    'bot_events_chart',
    'bot_traffic',
    'countries',
    'live_events',
]

export const CONTENT_CARD_SPAN: Record<LiveContentCardId, 'full' | 'half'> = {
    active_users_chart: 'half',
    top_paths: 'half',
    top_referrers: 'half',
    devices: 'half',
    browsers: 'half',
    top_countries: 'half',
    bot_events_chart: 'half',
    bot_traffic: 'half',
    countries: 'full',
    live_events: 'full',
}

export const mergeOrder = <T extends string>(persisted: readonly T[], defaults: readonly T[]): T[] => {
    const allowed = new Set<T>(defaults)
    const merged: T[] = []
    const seen = new Set<T>()
    for (const id of persisted) {
        if (allowed.has(id) && !seen.has(id)) {
            merged.push(id)
            seen.add(id)
        }
    }
    // Insert any missing default at its default-order position relative to the preceding
    // default that is already present — so newly-added cards slot in next to their
    // logical neighbors instead of being dumped at the end of a persisted layout.
    for (let i = 0; i < defaults.length; i++) {
        const id = defaults[i]
        if (seen.has(id)) {
            continue
        }
        let insertAt = 0
        for (let j = i - 1; j >= 0; j--) {
            const prev = defaults[j]
            if (seen.has(prev)) {
                insertAt = merged.indexOf(prev) + 1
                break
            }
        }
        merged.splice(insertAt, 0, id)
        seen.add(id)
    }
    return merged
}
