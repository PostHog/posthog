import api, { ApiConfig } from 'lib/api'
import { ApiError } from 'lib/api-error'
import { hogql } from 'lib/utils/hogql'

import { NodeKind, ProductKey } from '~/queries/schema/schema-general'
import {
    CyclotronJobFiltersType,
    CyclotronJobInvocationGlobals,
    HogFunctionConfigurationContextId,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import {
    errorTrackingFingerprintsList,
    errorTrackingIssuesRetrieve,
} from 'products/error_tracking/frontend/generated/api'
import type { ErrorTrackingIssueReadApi } from 'products/error_tracking/frontend/generated/api.schemas'

import { performWideEventsQueryInTwoPhases } from '../sampleEventsQuery'

export type SampleGlobalsLoader = (
    exampleGlobals: CyclotronJobInvocationGlobals,
    filters?: CyclotronJobFiltersType | null
) => Promise<CyclotronJobInvocationGlobals>

// An alert scoped to some health check kinds skips an event of any other kind, so the sample
// takes a kind the filters accept. Only an exact-match filter names an accepted kind. Any other
// operator, such as "is not", names kinds the alert excludes.
function sampleHealthCheckKind(filters?: CyclotronJobFiltersType | null): string {
    const kindFilter = filters?.properties?.find(
        (property) =>
            'key' in property &&
            property.key === 'kind' &&
            'operator' in property &&
            property.operator === PropertyOperator.Exact
    )
    const value = kindFilter && 'value' in kindFilter ? kindFilter.value : null
    const kind = Array.isArray(value) ? value[0] : value
    return typeof kind === 'string' && kind ? kind : 'test'
}

type SampleCandidate = { issueId: string; fingerprint: string }

// The fingerprints API lists the oldest fingerprints first, so try recent issues.
async function loadRecentlyActiveIssues(days: number): Promise<SampleCandidate[] | null> {
    try {
        const response = await api.queryHogQL<[string | null, string | null][]>(
            hogql`SELECT properties.$exception_issue_id, properties.$exception_fingerprint FROM events
                WHERE event = '$exception' AND timestamp > now() - INTERVAL ${days} DAY
                AND properties.$exception_issue_id IS NOT NULL AND properties.$exception_fingerprint IS NOT NULL
                ORDER BY timestamp DESC LIMIT 100`,
            { productKey: ProductKey.ERROR_TRACKING, name: `hog_function_error_tracking_sample_issues_${days}d` }
        )
        const byFingerprint = new Map<string, SampleCandidate>()
        for (const [issueId, fingerprint] of response.results) {
            if (issueId && fingerprint && !byFingerprint.has(fingerprint)) {
                byFingerprint.set(fingerprint, { issueId, fingerprint })
            }
        }
        return [...byFingerprint.values()].slice(0, 20)
    } catch {
        return null
    }
}

// An exception keeps the issue id it was ingested with, so ask for the issue that owns the fingerprint now.
async function retrieveCurrentIssue(projectId: string, candidate: SampleCandidate): Promise<ErrorTrackingIssueReadApi> {
    try {
        return await errorTrackingIssuesRetrieve(projectId, candidate.issueId, { fingerprint: candidate.fingerprint })
    } catch (error) {
        if (error instanceof ApiError && error.status === 308 && typeof error.data?.issue_id === 'string') {
            return await errorTrackingIssuesRetrieve(projectId, error.data.issue_id)
        }
        throw error
    }
}

// Filters on fingerprint, not issue id: live delivery sends the properties of the exception with this fingerprint.
async function loadLatestExceptionEvent(
    fingerprint: string
): Promise<{ properties: Record<string, any>; timestamp: string } | null> {
    try {
        const response = await performWideEventsQueryInTwoPhases({
            kind: NodeKind.EventsQuery,
            event: '$exception',
            select: ['*'],
            properties: [
                { type: PropertyFilterType.HogQL, key: hogql`properties.$exception_fingerprint = ${fingerprint}` },
            ],
            after: '-30d',
            orderBy: ['timestamp DESC'],
            limit: 1,
            tags: { productKey: ProductKey.ERROR_TRACKING, name: 'hog_function_error_tracking_sample_event' },
        })
        const event = response.results[0]?.[0]
        return event ? { properties: event.properties, timestamp: event.timestamp } : null
    } catch {
        return null
    }
}

/**
 * Per-context overrides for the "load sample globals" flow in the hog function test panel.
 * Contexts without an entry load the last event matching the configured filters.
 */
export const SAMPLE_GLOBALS_CONTEXTS: Partial<Record<HogFunctionConfigurationContextId, SampleGlobalsLoader>> = {
    'error-tracking': async (exampleGlobals) => {
        const projectId = String(ApiConfig.getCurrentProjectId())
        let candidates = await loadRecentlyActiveIssues(1)
        // Widen only after an empty day, never after a failed or timed-out query
        if (candidates?.length === 0) {
            candidates = await loadRecentlyActiveIssues(30)
        }
        if (!candidates?.length) {
            // The issues list API doesn't expose fingerprints, so start from fingerprint records.
            const response = await errorTrackingFingerprintsList(projectId, { limit: 20 })
            candidates = response.results.map((record) => ({
                issueId: record.issue_id,
                fingerprint: record.fingerprint,
            }))
        }
        const candidate = candidates[Math.floor(Math.random() * candidates.length)]
        if (!candidate) {
            return exampleGlobals
        }
        const [issue, exceptionEvent] = await Promise.all([
            retrieveCurrentIssue(projectId, candidate),
            loadLatestExceptionEvent(candidate.fingerprint),
        ])
        const properties: Record<string, any> = {
            name: issue.name ?? 'Unnamed issue',
            description: 'PostHog test alert',
            status: issue.status,
            severity: issue.severity,
            fingerprint: candidate.fingerprint,
        }
        if (issue.assignee) {
            // Real issue lifecycle events stringify the assignee as {"type":...,"id":...},
            // and omit the property entirely when the issue is unassigned
            properties.assignee = JSON.stringify({ type: issue.assignee.type, id: issue.assignee.id })
        }
        if (exceptionEvent) {
            properties.exception_timestamp = exceptionEvent.timestamp
        }
        return {
            ...exampleGlobals,
            event: {
                ...exampleGlobals.event,
                // Real issue lifecycle events use the issue id as the distinct_id
                distinct_id: issue.id,
                // Same order as live delivery in nodejs/src/cdp/utils.ts, so issue fields win.
                properties: { ...exceptionEvent?.properties, ...properties },
            },
        }
    },
    // Health alert templates read only this envelope. An empty title or summary renders an empty
    // Slack block, and Slack rejects the whole message.
    'health-alerts': async (exampleGlobals, filters) => ({
        ...exampleGlobals,
        event: {
            ...exampleGlobals.event,
            properties: {
                kind: sampleHealthCheckKind(filters),
                severity: 'warning',
                issue_id: 'test-issue-id',
                title: 'Test health check',
                summary: 'This is a test alert from PostHog',
                link: '/health',
                remediation: null,
                payload: {},
            },
        },
    }),
    // Placeholder ids, so a test delivery cannot be mistaken for a real report.
    'signals-reports': async (exampleGlobals) => {
        const reportId = '00000000-0000-0000-0000-000000000000'
        const reportUrl = `${exampleGlobals.project.url}/inbox/reports/${reportId}`
        return {
            ...exampleGlobals,
            event: {
                ...exampleGlobals.event,
                event: '$signals_report_ready',
                distinct_id: reportId,
                url: reportUrl,
                properties: {
                    report_id: reportId,
                    report_url: reportUrl,
                    priority: 'P2',
                    actionability: 'immediately_actionable',
                    source_products: ['error_tracking'],
                    source_products_text: 'error_tracking',
                    updated_at: new Date().toISOString(),
                },
            },
            person: undefined,
        }
    },
}
