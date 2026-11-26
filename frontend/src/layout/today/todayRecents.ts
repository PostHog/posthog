import { TODAY_AUTOMATE_RECENT_TYPES, TodayAutomateRecent } from './todayAutomateRecents'
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

export type TodayRecent =
    | TodayPeopleRecent
    | TodayMonitorRecent
    | TodayReleaseRecent
    | TodayAutomateRecent
    | TodayDataRecent

export type TodayRecentPane = 'people' | 'monitor' | 'release' | 'automate' | 'data'

/**
 * A scene logic that opens one record has a selector with this name. It gives the record as a recent, or null until
 * the record has loaded. It reads the logic's own record, so its name and href always belong together.
 */
export const TODAY_RECENT_KEY = 'todayRecent'

/** How Pinned and Recents name one type of record: after the record's name, and in its hover card. */
export interface TodayRecentTypeCopy {
    label: string
    description: string
}

export const TODAY_RECENTS_LIMIT = 10

interface TodayRecentByPane {
    people: TodayPeopleRecent
    monitor: TodayMonitorRecent
    release: TodayReleaseRecent
    automate: TodayAutomateRecent
    data: TodayDataRecent
}

/** The record types each pane claims. Monitor has no entry because it takes every record no other pane claims. */
const RECENT_TYPES_BY_PANE: Record<Exclude<TodayRecentPane, 'monitor'>, readonly string[]> = {
    people: TODAY_PEOPLE_RECENT_TYPES,
    release: ['release'],
    automate: TODAY_AUTOMATE_RECENT_TYPES,
    data: TODAY_DATA_RECENT_TYPES,
}

export function recentPane(recent: TodayRecent): TodayRecentPane {
    const claimed = Object.entries(RECENT_TYPES_BY_PANE).find(([, types]) => types.includes(recent.type))
    return (claimed?.[0] as TodayRecentPane | undefined) ?? 'monitor'
}

export function isPaneRecent<P extends TodayRecentPane>(recent: TodayRecent, pane: P): recent is TodayRecentByPane[P] {
    return recentPane(recent) === pane
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
