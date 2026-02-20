import { actions, events, kea, key, listeners, path, props, reducers } from 'kea'
import posthog from 'posthog-js'

import api from 'lib/api'
import { retryWithBackoff } from 'lib/utils'

import type { errorBoundaryLinkedIssueLogicType } from './errorBoundaryLinkedIssueLogicType'

export interface ErrorTrackingExternalUrl {
    url: string
    kind: string
}

export interface ErrorTrackingLookupByEventResponse {
    external_urls: ErrorTrackingExternalUrl[]
}

export interface ErrorBoundaryLinkedIssueLogicProps {
    eventUuid: string
    timestamp: string
}

// Poll 6 times, up to ~30 seconds, for an issue to be created for the given event UUID.
// If no issue is found after that, we give up and stop polling.
// Processing p95 is ~6 seconds in Grafana at time of writing this, so we should poll 4 times
// in most cases.
const MAX_POLL_ATTEMPTS = 6
const INITIAL_DELAY_MS = 1000
const BACKOFF_MULTIPLIER = 2

export const errorBoundaryLinkedIssueLogic = kea<errorBoundaryLinkedIssueLogicType>([
    path((key) => ['layout', 'ErrorBoundary', 'errorBoundaryLinkedIssueLogic', key]),
    props({} as ErrorBoundaryLinkedIssueLogicProps),
    key((props) => props.eventUuid),

    actions({
        startPolling: true,
        setExternalUrls: (externalUrls: ErrorTrackingExternalUrl[]) => ({ externalUrls }),
        setTimedOut: true,
    }),

    reducers({
        externalUrls: [[] as ErrorTrackingExternalUrl[], { setExternalUrls: (_, { externalUrls }) => externalUrls }],
        polling: [
            true,
            {
                setExternalUrls: () => false,
                setTimedOut: () => false,
            },
        ],
        timedOut: [false, { setTimedOut: () => true }],
    }),

    listeners(({ actions, props }) => ({
        startPolling: async () => {
            try {
                const result = await retryWithBackoff(
                    () => api.errorTracking.getGitHubIssueUrlsForEventUuid(props.eventUuid, props.timestamp),
                    {
                        maxAttempts: MAX_POLL_ATTEMPTS,
                        initialDelayMs: INITIAL_DELAY_MS,
                        backoffMultiplier: BACKOFF_MULTIPLIER,
                        shouldRetry: (e: unknown) => (e as any)?.status === 404,
                    }
                )
                actions.setExternalUrls(result.external_urls)
                posthog.capture('error_boundary_issue_lookup_completed', {
                    error_boundary_exception_id: props.eventUuid,
                    error_boundary_linked_issue_result: 'found_issue',
                    error_boundary_linked_issues: result.external_urls,
                })
            } catch {
                actions.setTimedOut()
                posthog.capture('error_boundary_issue_lookup_completed', {
                    error_boundary_exception_id: props.eventUuid,
                    error_boundary_linked_issue_result: 'timed_out',
                })
            }
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.startPolling()
        },
    })),
])
