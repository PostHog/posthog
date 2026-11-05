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

// pinned: the keys are part of the row's `people-sidebar-<row>` data-attr.
export const TODAY_PEOPLE_ROW_LABELS = {
    overview: 'Overview',
    feed: 'Feed',
    tasks: 'Tasks',
    persons: 'Persons',
    accounts: 'Accounts',
    cohorts: 'Cohorts',
    journeys: 'Journeys',
    notes: 'Notes',
    announcements: 'Announcements',
    feature_requests: 'Feature requests',
    support: 'Support',
} as const

export type TodayPeopleStaticRowKey = keyof typeof TODAY_PEOPLE_ROW_LABELS

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
