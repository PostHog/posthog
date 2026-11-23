import { TODAY_DATA_RECENT_TYPES, TodayDataRecent } from './todayDataRecents'
import type { TodayMonitorRecent } from './todayMonitor'
import { TODAY_PEOPLE_RECENT_TYPES, TodayPeopleRecent } from './todayPeople'

export interface TodayReleaseRecent {
    type: 'release'
    id: string
    name: string
    href: string
}

export interface StoredReleaseRecent extends TodayReleaseRecent {
    viewedAt: number
}

export type TodayRecent = TodayPeopleRecent | TodayMonitorRecent | TodayReleaseRecent | TodayDataRecent

export type TodayRecentPane = 'people' | 'monitor' | 'release' | 'data'

/**
 * A scene logic that opens one record has a selector with this name. It gives the record as a recent, or null until
 * the record has loaded. It reads the logic's own record, so its name and href always belong together.
 */
export const TODAY_RECENT_KEY = 'todayRecent'

export const TODAY_RECENTS_LIMIT = 10

export function isPeopleRecent(recent: TodayRecent): recent is TodayPeopleRecent {
    return (TODAY_PEOPLE_RECENT_TYPES as readonly string[]).includes(recent.type)
}

export function isDataRecent(recent: TodayRecent): recent is TodayDataRecent {
    return (TODAY_DATA_RECENT_TYPES as readonly string[]).includes(recent.type)
}

export function isReleaseRecent(recent: TodayRecent): recent is TodayReleaseRecent {
    return recent.type === 'release'
}

/** Monitor takes every record that no other pane claims. */
export function isMonitorRecent(recent: TodayRecent): recent is TodayMonitorRecent {
    return !isPeopleRecent(recent) && !isDataRecent(recent) && !isReleaseRecent(recent)
}

export function recentPane(recent: TodayRecent): TodayRecentPane {
    if (isPeopleRecent(recent)) {
        return 'people'
    }
    if (isDataRecent(recent)) {
        return 'data'
    }
    return isReleaseRecent(recent) ? 'release' : 'monitor'
}

/** Puts a visit first. Reloading the same page changes nothing, so the list stays stable while a page loads. */
export function addTodayRecent<T extends TodayRecent>(recents: T[], recent: T): T[] {
    const [first] = recents
    if (first?.href === recent.href && first.name === recent.name) {
        return recents
    }
    return [recent, ...recents.filter((item) => item.href !== recent.href)].slice(0, TODAY_RECENTS_LIMIT)
}

/** The id of a recent's row, for the active row and the row's own value. */
export function recentRowKey(href: string): string {
    return `recent:${href}`
}
