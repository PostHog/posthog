import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { ErrorTrackingSpikeEvent } from 'lib/components/Errors/types'
import { dayjs } from 'lib/dayjs'

import { DateRange, ErrorTrackingIssue, ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { errorTrackingIssueQuery } from 'products/error_tracking/frontend/queries'
import { ERROR_TRACKING_LISTING_RESOLUTION } from 'products/error_tracking/frontend/utils'

import type { inboxErrorTrackingIssueLogicType } from './inboxErrorTrackingIssueLogicType'

export type InboxErrorTrackingIssueSourceType = 'issue_created' | 'issue_reopened' | 'issue_spiking'

export interface InboxErrorTrackingIssueLogicProps {
    issueId: string
    fingerprint: string
    sourceType: InboxErrorTrackingIssueSourceType
}

/** Aggregations + volume + last_seen for the issue, mirroring the error tracking scene's `loadSummary`. */
export interface InboxErrorTrackingIssueSummary {
    last_seen?: string
    first_seen?: string
    aggregations: ErrorTrackingIssue['aggregations']
}

/** Window anchored on the signal: the last 30 days, which comfortably covers a freshly emitted issue. */
function defaultDateRange(): DateRange {
    return {
        date_from: dayjs().subtract(30, 'day').toISOString(),
        date_to: dayjs().toISOString(),
    }
}

/**
 * The summary is an optional aggregation read. Under ClickHouse pressure the query API throttles
 * (429 "Too many queries are running…") or returns a transient 5xx. Those are expected and the card
 * can still render the relational issue row without aggregations, so we swallow them rather than let
 * them bubble up as a handled frontend exception. Genuinely unexpected errors still propagate.
 */
function isExpectedSummaryQueryFailure(error: unknown): boolean {
    if (!(error instanceof ApiError)) {
        return false
    }
    // 429 (throttled / concurrency limit) and any 5xx (capacity, gateway) are transient by nature.
    return error.status === 429 || (error.status !== undefined && error.status >= 500)
}

/**
 * Loads the live error tracking issue (relational row + summary aggregations, plus spike events for
 * spiking signals) so the inbox signal card can embed the real issue row read-only. Keyed by
 * issue id + fingerprint so distinct signals don't share state.
 */
export const inboxErrorTrackingIssueLogic = kea<inboxErrorTrackingIssueLogicType>([
    path((key) => ['scenes', 'inbox', 'components', 'signalCards', 'inboxErrorTrackingIssueLogic', key]),
    props({} as InboxErrorTrackingIssueLogicProps),
    key((props) => `${props.issueId}:${props.fingerprint}`),

    actions({
        setMergedToIssueId: (issueId: string | null) => ({ issueId }),
        setSummaryUnavailable: true,
    }),

    reducers({
        // When `getIssue` 308-redirects (the issue was merged away), capture the surviving issue id
        // so the card can fall back to a link rather than render a stale row.
        mergedToIssueId: [
            null as string | null,
            {
                setMergedToIssueId: (_, { issueId }) => issueId,
            },
        ],
        // True once a summary load was throttled/failed transiently, so the card can show a quiet hint
        // instead of just a missing sparkline. Reset whenever a fresh summary load starts.
        summaryUnavailable: [
            false,
            {
                loadSummary: () => false,
                setSummaryUnavailable: () => true,
            },
        ],
    }),

    loaders(({ props, actions }) => ({
        issue: [
            null as ErrorTrackingRelationalIssue | null,
            {
                loadIssue: async () => {
                    try {
                        return await api.errorTracking.getIssue(props.issueId, props.fingerprint)
                    } catch (error: any) {
                        // 308 means the issue was merged into another; surface the target for the fallback.
                        if (error?.status === 308 && error?.data && 'issue_id' in error.data) {
                            actions.setMergedToIssueId(error.data.issue_id)
                        }
                        throw error
                    }
                },
            },
        ],
        summary: [
            null as InboxErrorTrackingIssueSummary | null,
            {
                loadSummary: async () => {
                    let response
                    try {
                        response = await api.query(
                            errorTrackingIssueQuery({
                                issueId: props.issueId,
                                dateRange: defaultDateRange(),
                                filterTestAccounts: false,
                                withAggregations: true,
                            }),
                            { refresh: 'blocking' }
                        )
                    } catch (error) {
                        // The aggregation summary is optional; a throttle/5xx shouldn't surface as a
                        // handled frontend exception. Degrade to the row without a sparkline instead.
                        if (isExpectedSummaryQueryFailure(error)) {
                            actions.setSummaryUnavailable()
                            return null
                        }
                        throw error
                    }
                    if (!response.results.length) {
                        return null
                    }
                    const summary = response.results[0]
                    if (!summary.aggregations) {
                        return null
                    }
                    return {
                        first_seen: summary.first_seen,
                        last_seen: summary.last_seen,
                        aggregations: summary.aggregations,
                    }
                },
            },
        ],
        spikeEvents: [
            [] as ErrorTrackingSpikeEvent[],
            {
                loadSpikeEvents: async () => {
                    const { date_from, date_to } = defaultDateRange()
                    const response = await api.errorTracking.getSpikeEvents({
                        issueIds: [props.issueId],
                        dateFrom: date_from ?? undefined,
                        dateTo: date_to ?? undefined,
                    })
                    return response.results
                },
            },
        ],
    })),

    selectors({
        /** True once the issue load failed (not found, merged away, or otherwise unavailable). */
        mergedFailed: [(s) => [s.issueLoading, s.issue], (issueLoading, issue) => !issueLoading && !issue],

        /** Assembled `ErrorTrackingIssue` for the read-only row: relational issue merged with summary. */
        mergedIssue: [
            (s) => [s.issue, s.summary],
            (
                issue: ErrorTrackingRelationalIssue | null,
                summary: InboxErrorTrackingIssueSummary | null
            ): ErrorTrackingIssue | null => {
                if (!issue) {
                    return null
                }
                return {
                    ...issue,
                    last_seen: summary?.last_seen ?? issue.first_seen,
                    aggregations: summary?.aggregations,
                    // The relational issue carries no library; the runtime icon falls back to unknown.
                    library: null,
                }
            },
        ],

        /** Spike-highlight resolution shared with the listing sparkline. */
        sparklineResolution: [() => [], () => ERROR_TRACKING_LISTING_RESOLUTION],
    }),

    listeners(({ props, actions }) => ({
        loadIssueSuccess: () => {
            actions.setMergedToIssueId(null)
        },
        loadIssueFailure: () => {
            // No-op beyond the 308 capture in the loader; `mergedFailed` drives the fallback UI.
        },
        loadSummarySuccess: () => {
            if (props.sourceType === 'issue_spiking') {
                actions.loadSpikeEvents()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadIssue()
        actions.loadSummary()
    }),
])
