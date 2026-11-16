import { isUnderPath } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

export type TodayPeopleRecentType = 'person' | 'group' | 'cohort' | 'account' | 'ticket'

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
