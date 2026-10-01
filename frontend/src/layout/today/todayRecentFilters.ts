import { TodayWorkItem } from './todayWorkItems'

export type TodayRecentCreatedByFilter = 'anyone' | 'me' | 'others'
export type TodayRecentStatusFilter = 'any' | 'unread'
export type TodayRecentPinnedFilter = 'any' | 'pinned'
export type TodayRecentEnvironmentFilter = 'any' | 'local' | 'cloud'

export interface TodayRecentFilters {
    status: TodayRecentStatusFilter
    createdBy: TodayRecentCreatedByFilter
    pinned: TodayRecentPinnedFilter
    environment: TodayRecentEnvironmentFilter
    /** Sources to keep. An empty list keeps every source. */
    sources: string[]
}

export const DEFAULT_RECENT_FILTERS: TodayRecentFilters = {
    status: 'any',
    createdBy: 'anyone',
    pinned: 'any',
    environment: 'any',
    sources: [],
}

/** What a filter reads besides the item itself. */
export interface TodayRecentFilterContext {
    userId: number | null
    unreadIds: Set<string>
    pinnedIds: Set<string>
}

type FilterOptions<T extends string> = { value: T; label: string; dotClassName?: string }[]

// Like PostHog Desktop. The web has no "Needs input" signal, so Status offers unread only.
export const RECENT_STATUS_OPTIONS: FilterOptions<TodayRecentStatusFilter> = [
    { value: 'any', label: 'Any status' },
    { value: 'unread', label: 'Unread', dotClassName: 'bg-primary' },
]

export const RECENT_CREATED_BY_OPTIONS: FilterOptions<TodayRecentCreatedByFilter> = [
    { value: 'anyone', label: 'Anyone' },
    { value: 'me', label: 'Me' },
    { value: 'others', label: 'Other people' },
]

export const RECENT_PINNED_OPTIONS: FilterOptions<TodayRecentPinnedFilter> = [
    { value: 'any', label: 'All sessions' },
    { value: 'pinned', label: 'Pinned only' },
]

export const RECENT_ENVIRONMENT_OPTIONS: FilterOptions<TodayRecentEnvironmentFilter> = [
    { value: 'any', label: 'Anywhere' },
    { value: 'local', label: 'Local' },
    { value: 'cloud', label: 'Cloud' },
]

const SOURCE_LABELS: Record<string, string> = {
    user_created: 'Manual',
    posthog_ai: 'PostHog AI',
    slack: 'Slack',
    signal_report: 'Signals',
    signals_scout: 'Signals scout',
    support_queue: 'Support',
    session_summaries: 'Session summary',
    error_tracking: 'Error tracking',
    eval_clusters: 'Evals',
    task_analysis: 'Task analysis',
    hogdesk: 'HogDesk',
    mcp_analytics: 'MCP analytics',
    review_hog: 'ReviewHog',
}

export function recentSourceLabel(source: string): string {
    const words = source.replaceAll('_', ' ')
    return SOURCE_LABELS[source] ?? words.charAt(0).toUpperCase() + words.slice(1)
}

/** Saved filters from before a filter existed lack it, so that filter starts at its default. */
export function withRecentFilterDefaults(saved: Partial<TodayRecentFilters>): TodayRecentFilters {
    return { ...DEFAULT_RECENT_FILTERS, ...saved }
}

/** The search box is left out: it shows its own query, while a filter in a closed menu shows nothing. */
export function hasActiveRecentFilters(filters: TodayRecentFilters): boolean {
    return (
        filters.status !== DEFAULT_RECENT_FILTERS.status ||
        filters.createdBy !== DEFAULT_RECENT_FILTERS.createdBy ||
        filters.pinned !== DEFAULT_RECENT_FILTERS.pinned ||
        filters.environment !== DEFAULT_RECENT_FILTERS.environment ||
        filters.sources.length > 0
    )
}

/** The sources in the list plus any still selected, so a selection can always be undone. */
export function recentSourceOptions(items: TodayWorkItem[], selected: string[]): string[] {
    const sources = new Set(selected)
    for (const item of items) {
        if (item.source) {
            sources.add(item.source)
        }
    }
    return [...sources].sort()
}

export function filterRecentItems(
    items: TodayWorkItem[],
    query: string,
    filters: TodayRecentFilters,
    { userId, unreadIds, pinnedIds }: TodayRecentFilterContext
): TodayWorkItem[] {
    const needle = query.trim().toLowerCase()
    return items.filter((item) => {
        if (needle && !(item.title || '').toLowerCase().includes(needle)) {
            return false
        }
        if (filters.status === 'unread' && !unreadIds.has(item.id)) {
            return false
        }
        if (filters.pinned === 'pinned' && !pinnedIds.has(item.id)) {
            return false
        }
        // A chat, or a session that never ran, has no environment, so it matches neither.
        if (filters.environment !== 'any' && item.runEnvironment !== filters.environment) {
            return false
        }
        if (filters.createdBy !== 'anyone') {
            // A deleted creator is neither you nor a known other person.
            if (item.createdById === null) {
                return false
            }
            const mine = item.createdById === userId
            if (filters.createdBy === 'me' ? !mine : mine) {
                return false
            }
        }
        return !filters.sources.length || (item.source !== null && filters.sources.includes(item.source))
    })
}
