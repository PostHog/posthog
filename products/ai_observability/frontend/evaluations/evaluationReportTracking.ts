import posthog from 'posthog-js'

import type { ReportDestination } from './evaluationReportLogic'

/**
 * Usage tracking for evaluation reports on the evaluation page.
 *
 * These events cover what autocapture cannot see: drawer opens from a link or a key, how long a report stays open, and
 * saved outcomes. Clicks carry an `llma-evaluation-report*` `data-attr`, so count them from `$autocapture` instead.
 * The server records config writes as `llma evaluation report created` and `updated`.
 */

// pinned: event names and property keys. Dashboards and insights read them, so a rename breaks them.
const EVENTS = {
    tabViewed: 'llma evaluation reports tab viewed',
    drawerOpened: 'llma evaluation report drawer opened',
    drawerStepped: 'llma evaluation report drawer stepped',
    drawerClosed: 'llma evaluation report drawer closed',
    generateRequested: 'llma evaluation report generate requested',
    destinationsSaved: 'llma evaluation report destinations saved',
} as const

export type ReportDrawerSource = 'link' | 'runs_card' | 'reports_tab' | 'overview_card'

// The overview card opens a report by navigating to the evaluation page, so it hands the source over here.
let pendingDrawerSource: ReportDrawerSource | null = null

export function markNextDrawerSource(source: ReportDrawerSource): void {
    pendingDrawerSource = source
}

export function takeNextDrawerSource(): ReportDrawerSource | null {
    const source = pendingDrawerSource
    pendingDrawerSource = null
    return source
}

export const evaluationReportTracking = {
    tabViewed: (props: { report_count: number; has_destination: boolean; enabled: boolean }): void => {
        posthog.capture(EVENTS.tabViewed, props)
    },
    drawerOpened: (props: {
        source: ReportDrawerSource
        delivery_status: string | null
        has_destination: boolean
        report_age_hours: number | null
    }): void => {
        posthog.capture(EVENTS.drawerOpened, props)
    },
    drawerStepped: (direction: 'previous' | 'next'): void => {
        posthog.capture(EVENTS.drawerStepped, { direction })
    },
    drawerClosed: (props: { seconds_open: number; steps: number }): void => {
        posthog.capture(EVENTS.drawerClosed, props)
    },
    generateRequested: (): void => {
        posthog.capture(EVENTS.generateRequested)
    },
    destinationsSaved: (props: { destination_types: ReportDestination[]; added: ReportDestination[] }): void => {
        posthog.capture(EVENTS.destinationsSaved, props)
    },
}
