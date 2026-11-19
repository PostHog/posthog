import { isUnderPath } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { HrefPin, hrefPinsFromShortcuts } from '~/layout/today/sidebar/hrefPins'
import { FileSystemEntry } from '~/queries/schema/schema-general'

export const TODAY_PEOPLE_RECENT_TYPES = ['person', 'group', 'cohort', 'account', 'ticket'] as const

export type TodayPeopleRecentType = (typeof TODAY_PEOPLE_RECENT_TYPES)[number]

export interface TodayPeopleRecent {
    type: TodayPeopleRecentType
    name: string
    href: string
}

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

export type TodayPeoplePin = HrefPin<TodayPeopleRecentType>

export function peoplePinsFromShortcuts(shortcuts: FileSystemEntry[]): TodayPeoplePin[] {
    return hrefPinsFromShortcuts(shortcuts, TODAY_PEOPLE_RECENT_TYPES)
}
