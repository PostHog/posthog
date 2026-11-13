import api, { ApiConfig } from 'lib/api'
import { hogql } from 'lib/utils/hogql'

import { ProductKey } from '~/queries/schema/schema-general'
import {
    CyclotronJobFiltersType,
    CyclotronJobInvocationGlobals,
    HogFunctionConfigurationContextId,
    PropertyOperator,
} from '~/types'

import {
    errorTrackingFingerprintsList,
    errorTrackingIssuesRetrieve,
} from 'products/error_tracking/frontend/generated/api'

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

// The fingerprints API lists the oldest fingerprints first, and those rarely have a recent exception.
async function loadRecentlyActiveIssues(): Promise<SampleCandidate[]> {
    try {
        const response = await api.queryHogQL<[string, string][]>(
            hogql`SELECT toString(issue_id), argMax(properties.$exception_fingerprint, timestamp) FROM events
                WHERE event = '$exception' AND timestamp > now() - INTERVAL 1 DAY AND issue_id IS NOT NULL
                GROUP BY issue_id ORDER BY max(timestamp) DESC LIMIT 20`,
            { productKey: ProductKey.ERROR_TRACKING, name: 'hog_function_error_tracking_sample_issues' }
        )
        return response.results
            .filter(([, fingerprint]) => fingerprint)
            .map(([issueId, fingerprint]) => ({ issueId, fingerprint }))
    } catch {
        return []
    }
}

// Filters on fingerprint, not issue id: live delivery sends the properties of the exception with this fingerprint.
async function loadLatestExceptionEvent(
    fingerprint: string
): Promise<{ properties: Record<string, any>; timestamp: string } | null> {
    try {
        const response = await api.queryHogQL<[string, string][]>(
            hogql`SELECT properties, timestamp FROM events
                WHERE event = '$exception' AND properties.$exception_fingerprint = ${fingerprint}
                AND timestamp > now() - INTERVAL 30 DAY
                ORDER BY timestamp DESC LIMIT 1`,
            { productKey: ProductKey.ERROR_TRACKING, name: 'hog_function_error_tracking_sample_event' }
        )
        const row = response.results[0]
        if (!row) {
            return null
        }
        const [properties, timestamp] = row
        return { properties: JSON.parse(properties), timestamp }
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
        let candidates = await loadRecentlyActiveIssues()
        if (!candidates.length) {
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
            errorTrackingIssuesRetrieve(projectId, candidate.issueId),
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
}
