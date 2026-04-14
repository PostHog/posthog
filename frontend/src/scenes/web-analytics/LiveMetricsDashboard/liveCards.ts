export type LiveStatCardId = 'users_online' | 'unique_visitors' | 'pageviews'

export type LiveContentCardId =
    | 'active_users_chart'
    | 'top_paths'
    | 'top_referrers'
    | 'devices'
    | 'browsers'
    | 'countries'
    | 'live_events'

export const DEFAULT_STAT_ORDER: readonly LiveStatCardId[] = ['users_online', 'unique_visitors', 'pageviews']

export const DEFAULT_CONTENT_ORDER: readonly LiveContentCardId[] = [
    'active_users_chart',
    'top_paths',
    'top_referrers',
    'devices',
    'browsers',
    'countries',
    'live_events',
]

export const CONTENT_CARD_SPAN: Record<LiveContentCardId, 'full' | 'half'> = {
    active_users_chart: 'half',
    top_paths: 'half',
    top_referrers: 'half',
    devices: 'half',
    browsers: 'half',
    countries: 'full',
    live_events: 'full',
}

export const mergeOrder = <T extends string>(persisted: readonly T[], defaults: readonly T[]): T[] => {
    const allowed = new Set<T>(defaults)
    const seen = new Set<T>()
    const merged: T[] = []
    for (const id of persisted) {
        if (allowed.has(id) && !seen.has(id)) {
            merged.push(id)
            seen.add(id)
        }
    }
    for (const id of defaults) {
        if (!seen.has(id)) {
            merged.push(id)
        }
    }
    return merged
}
