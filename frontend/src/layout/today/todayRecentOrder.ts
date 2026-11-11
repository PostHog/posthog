import { Dayjs, dayjs } from 'lib/dayjs'

import { TodayWorkItem, groupByDay } from './todayWorkItems'

export type TodayRecentSort = 'recent' | 'created' | 'alpha'
export type TodayRecentGrouping = 'date' | 'space' | 'repository'

export const DEFAULT_RECENT_SORT: TodayRecentSort = 'recent'
export const DEFAULT_RECENT_GROUPING: TodayRecentGrouping = 'date'

export const RECENT_GROUPING_OPTIONS: { value: TodayRecentGrouping; label: string }[] = [
    { value: 'date', label: 'Date' },
    { value: 'space', label: 'Space' },
    { value: 'repository', label: 'Repository' },
]

export const RECENT_SORT_OPTIONS: { value: TodayRecentSort; label: string }[] = [
    { value: 'recent', label: 'Recent activity' },
    { value: 'created', label: 'Date created' },
    { value: 'alpha', label: 'Name' },
]

export interface TodayRecentSection {
    key: string
    /** Null for a run with nothing to call it, like an alphabetical list. */
    label: string | null
    items: TodayWorkItem[]
}

function timeOf(timestamp: string | null): number {
    return timestamp ? dayjs(timestamp).valueOf() : 0
}

export function sortRecentItems(items: TodayWorkItem[], sort: TodayRecentSort): TodayWorkItem[] {
    return [...items].sort((first, second) =>
        sort === 'alpha'
            ? first.title.localeCompare(second.title)
            : sort === 'created'
              ? timeOf(second.createdAt) - timeOf(first.createdAt)
              : timeOf(second.timestamp) - timeOf(first.timestamp)
    )
}

/** One section per key, in first-seen order, with the fallback section last. */
function keyedSections(
    items: TodayWorkItem[],
    resolve: (item: TodayWorkItem) => { key: string; label: string } | null,
    fallback: { key: string; label: string }
): TodayRecentSection[] {
    const sections = new Map<string, TodayRecentSection>()
    for (const item of items) {
        const { key, label } = resolve(item) ?? fallback
        const section = sections.get(key)
        if (section) {
            section.items.push(item)
        } else {
            sections.set(key, { key, label, items: [item] })
        }
    }
    const all = [...sections.values()]
    const known = all.filter((section) => section.key !== fallback.key)
    return [...known, ...all.filter((section) => section.key === fallback.key)]
}

/** Cuts a sorted list into sections. Days follow the time the list is sorted by, so each day is one run. */
export function groupRecentItems(
    items: TodayWorkItem[],
    sort: TodayRecentSort,
    grouping: TodayRecentGrouping,
    spaceNames: Record<string, string>,
    now: Dayjs = dayjs()
): TodayRecentSection[] {
    if (!items.length) {
        return []
    }
    if (grouping === 'space') {
        return keyedSections(
            items,
            (item) =>
                item.channel && spaceNames[item.channel]
                    ? { key: `space:${item.channel}`, label: spaceNames[item.channel] }
                    : null,
            { key: 'space:none', label: 'No space' }
        )
    }
    if (grouping === 'repository') {
        return keyedSections(
            items,
            (item) =>
                item.repository ? { key: `repo:${item.repository.toLowerCase()}`, label: item.repository } : null,
            { key: 'repo:none', label: 'No repository' }
        )
    }
    if (sort === 'alpha') {
        return [{ key: 'all', label: null, items }]
    }
    return groupByDay(items, now, sort === 'created' ? 'createdAt' : 'timestamp')
}
