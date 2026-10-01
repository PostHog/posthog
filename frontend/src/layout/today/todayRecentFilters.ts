import { TodayWorkItem } from './todayWorkItems'

export type TodayRecentCreatedByFilter = 'anyone' | 'me' | 'others'

export interface TodayRecentFilters {
    createdBy: TodayRecentCreatedByFilter
    /** Sources to keep. An empty list keeps every source. */
    sources: string[]
}

export const DEFAULT_RECENT_FILTERS: TodayRecentFilters = { createdBy: 'anyone', sources: [] }

export const RECENT_CREATED_BY_OPTIONS: { value: TodayRecentCreatedByFilter; label: string }[] = [
    { value: 'anyone', label: 'Anyone' },
    { value: 'me', label: 'Me' },
    { value: 'others', label: 'Other people' },
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

/** The search box is left out: it shows its own query, while a filter in a closed menu shows nothing. */
export function hasActiveRecentFilters(filters: TodayRecentFilters): boolean {
    return filters.createdBy !== DEFAULT_RECENT_FILTERS.createdBy || filters.sources.length > 0
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
    userId: number | null
): TodayWorkItem[] {
    const needle = query.trim().toLowerCase()
    return items.filter((item) => {
        if (needle && !(item.title || '').toLowerCase().includes(needle)) {
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
