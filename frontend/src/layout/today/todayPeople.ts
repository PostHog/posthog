import { isUnderPath } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { pinKey } from '~/layout/today/sidebar/sidebarPinsLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'

const TODAY_PEOPLE_RECENT_TYPES = ['person', 'group', 'cohort', 'account', 'ticket'] as const

export type TodayPeopleRecentType = (typeof TODAY_PEOPLE_RECENT_TYPES)[number]

export interface TodayPeopleRecent {
    type: TodayPeopleRecentType
    name: string
    href: string
}

/**
 * A scene logic that opens one record has a selector with this name. It gives the record as a recent, or null until
 * the record has loaded. It reads the logic's own record, so its name and href always belong together.
 */
export const TODAY_PEOPLE_RECENT_KEY = 'todayPeopleRecent'

export function isPeopleListPath(path: string): boolean {
    return (
        path === urls.persons() ||
        path === urls.cohorts() ||
        /^\/groups\/[^/]+(\/new)?$/.test(path) ||
        isUnderPath(path, urls.customerAnalytics()) ||
        isUnderPath(path, urls.supportDashboard())
    )
}

/** One person, group or cohort. Other panes link to these, so a visit from one of them keeps that pane open. */
export function isPeopleDetailPath(path: string): boolean {
    return (
        !isPeopleListPath(path) &&
        (isUnderPath(path, '/person') ||
            isUnderPath(path, urls.persons()) ||
            isUnderPath(path, urls.cohorts()) ||
            isUnderPath(path, '/groups'))
    )
}

/** The id of a recent's row, for the active row and the row's own value. */
export function peopleRecentRowKey(href: string): string {
    return `recent:${href}`
}

/** A pinned person, group, cohort, account or ticket, with the key its sidebar row slides in under. */
export interface TodayPeoplePin extends TodayPeopleRecent {
    key: string
}

function isPeopleType(type: string | undefined): type is TodayPeopleRecentType {
    return (TODAY_PEOPLE_RECENT_TYPES as readonly (string | undefined)[]).includes(type)
}

/**
 * The People pane's pins among all shortcuts, in shortcut order. A People pin keys on its href, which is also how a
 * cohort starred in the classic navigation is found, so that star shows here too.
 */
export function peoplePinsFromShortcuts(shortcuts: FileSystemEntry[]): TodayPeoplePin[] {
    const pins = new Map<string, TodayPeoplePin>()
    for (const shortcut of shortcuts) {
        if (!shortcut.href || !isPeopleType(shortcut.type)) {
            continue
        }
        const key = pinKey(shortcut.type, shortcut.href)
        if (!pins.has(key)) {
            pins.set(key, {
                key,
                type: shortcut.type,
                name: splitPath(shortcut.path).at(-1) ?? shortcut.path,
                href: shortcut.href,
            })
        }
    }
    return [...pins.values()]
}
