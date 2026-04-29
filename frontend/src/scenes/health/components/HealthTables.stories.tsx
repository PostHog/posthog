import type { Meta, StoryFn } from '@storybook/react'

import DataModelingDetailContent from '../categoryDetail/categories/DataModelingDetailContent'
import { SdkOutdatedRenderer } from '../renderers/SdkOutdatedRenderer'
import type { HealthIssue, HealthIssueSeverity } from '../types'
import { DataModelingHealthTable } from './DataModelingHealthTable'
import { IngestionWarningTable } from './IngestionWarningTable'
import { PipelineHealthTable } from './PipelineHealthTable'
import { WebAnalyticsHealthTable } from './WebAnalyticsHealthTable'

function createMockIssue(
    id: string,
    overrides: Partial<HealthIssue> & { kind: string; payload: Record<string, any> }
): HealthIssue {
    return {
        id,
        severity: 'warning' as HealthIssueSeverity,
        status: 'active',
        dismissed: false,
        created_at: '2025-01-14T18:30:00Z',
        updated_at: '2025-01-14T18:30:00Z',
        resolved_at: null,
        ...overrides,
    }
}

const DATA_MODELING_ISSUES: HealthIssue[] = [
    createMockIssue('dm-1', {
        kind: 'materialized_view_failure',
        severity: 'critical',
        payload: {
            pipeline_name: 'revenue_analytics_monthly',
            error: 'Query returned no results for the last 7 days',
        },
        created_at: '2025-01-14T10:00:00Z',
    }),
    createMockIssue('dm-2', {
        kind: 'materialized_view_failure',
        severity: 'warning',
        payload: {
            pipeline_name: 'session_replay_events_v2',
            error: 'Memory limit exceeded during aggregation step',
        },
        created_at: '2025-01-13T14:20:00Z',
    }),
    createMockIssue('dm-3', {
        kind: 'materialized_view_failure',
        severity: 'info',
        payload: {
            pipeline_name: 'web_vitals_daily',
            error: null,
        },
        created_at: '2025-01-12T09:00:00Z',
    }),
]

const DATA_MODELING_DISMISSED: HealthIssue[] = [
    createMockIssue('dmd-1', {
        kind: 'materialized_view_failure',
        severity: 'critical',
        dismissed: true,
        payload: {
            pipeline_name: 'revenue_analytics_monthly',
            error: 'Query returned no results for the last 7 days',
        },
    }),
    createMockIssue('dmd-2', {
        kind: 'materialized_view_failure',
        severity: 'warning',
        payload: {
            pipeline_name: 'session_replay_events_v2',
            error: 'Memory limit exceeded during aggregation step',
        },
    }),
    createMockIssue('dmd-3', {
        kind: 'materialized_view_failure',
        severity: 'info',
        dismissed: true,
        payload: {
            pipeline_name: 'web_vitals_daily',
            error: 'Timeout while waiting for merge',
        },
    }),
]

const INGESTION_WARNING_ISSUES: HealthIssue[] = [
    createMockIssue('iw-1', {
        kind: 'ingestion_warning',
        severity: 'critical',
        payload: {
            warning_type: 'cannot_merge_already_identified',
            affected_count: 12453,
            last_seen_at: '2025-01-14T17:45:00Z',
        },
        created_at: '2025-01-14T08:00:00Z',
    }),
    createMockIssue('iw-2', {
        kind: 'ingestion_warning',
        severity: 'warning',
        payload: {
            warning_type: 'cannot_merge_with_illegal_distinct_id',
            affected_count: 87,
            last_seen_at: '2025-01-13T22:10:00Z',
        },
        created_at: '2025-01-13T12:00:00Z',
    }),
    createMockIssue('iw-3', {
        kind: 'ingestion_warning',
        severity: 'info',
        payload: {
            warning_type: 'event_timestamp_in_future',
            affected_count: 3,
            last_seen_at: '2025-01-12T16:30:00Z',
        },
        created_at: '2025-01-12T10:00:00Z',
    }),
]

const PIPELINE_ISSUES: HealthIssue[] = [
    createMockIssue('pipe-1', {
        kind: 'external_data_failure',
        severity: 'critical',
        payload: {
            pipeline_name: 'Stripe import',
            source_type: 'Stripe',
            error: 'Authentication failed: API key expired',
        },
        created_at: '2025-01-14T16:00:00Z',
    }),
    createMockIssue('pipe-2', {
        kind: 'external_data_failure',
        severity: 'warning',
        payload: {
            pipeline_name: 'Hubspot contacts sync',
            source_type: 'unknown',
            error: 'Rate limit exceeded, will retry',
        },
        created_at: '2025-01-13T20:00:00Z',
    }),
    createMockIssue('pipe-3', {
        kind: 'external_data_failure',
        severity: 'info',
        payload: {
            pipeline_name: 'Salesforce deals',
            error: null,
        },
        created_at: '2025-01-12T11:00:00Z',
    }),
]

const WEB_ANALYTICS_ISSUES: HealthIssue[] = [
    createMockIssue('wa-1', {
        kind: 'no_live_events',
        severity: 'critical',
        payload: {},
        created_at: '2025-01-14T12:00:00Z',
    }),
    createMockIssue('wa-2', {
        kind: 'no_pageleave_events',
        severity: 'warning',
        payload: {},
        created_at: '2025-01-14T12:00:00Z',
    }),
    createMockIssue('wa-3', {
        kind: 'scroll_depth',
        severity: 'info',
        payload: {},
        created_at: '2025-01-13T12:00:00Z',
    }),
    createMockIssue('wa-4', {
        kind: 'authorized_urls',
        severity: 'warning',
        payload: {},
        created_at: '2025-01-13T12:00:00Z',
    }),
    createMockIssue('wa-5', {
        kind: 'reverse_proxy',
        severity: 'info',
        payload: {},
        created_at: '2025-01-12T12:00:00Z',
    }),
    createMockIssue('wa-6', {
        kind: 'web_vitals',
        severity: 'info',
        payload: {},
        created_at: '2025-01-12T12:00:00Z',
    }),
]

const SDK_OUTDATED_ISSUE: HealthIssue = createMockIssue('sdk-1', {
    kind: 'sdk_outdated',
    severity: 'warning',
    payload: {
        sdk_name: 'web',
        latest_version: '1.142.0',
        usage: [
            {
                lib_version: '1.142.0',
                count: 84210,
                max_timestamp: '2025-01-15T09:30:00Z',
                release_date: '2025-01-10T00:00:00Z',
                is_latest: true,
            },
            {
                lib_version: '1.138.4',
                count: 12453,
                max_timestamp: '2025-01-14T22:15:00Z',
                release_date: '2024-12-18T00:00:00Z',
                is_latest: false,
            },
            {
                lib_version: '1.130.0',
                count: 312,
                max_timestamp: '2025-01-12T06:00:00Z',
                release_date: '2024-10-02T00:00:00Z',
                is_latest: false,
            },
        ],
    },
})

const SDK_OUTDATED_EMPTY_ISSUE: HealthIssue = createMockIssue('sdk-2', {
    kind: 'sdk_outdated',
    severity: 'info',
    payload: {
        sdk_name: 'web',
        latest_version: '1.142.0',
    },
})

const noop = (): void => {}

const meta: Meta = {
    title: 'Scenes-App/Health/Tables',
    parameters: {
        mockDate: '2025-01-15',
        viewMode: 'story',
    },
}
export default meta

export const DataModelingDefault: StoryFn = () => (
    <DataModelingHealthTable issues={DATA_MODELING_ISSUES} onDismiss={noop} onUndismiss={noop} />
)

export const DataModelingEmpty: StoryFn = () => (
    <DataModelingHealthTable issues={[]} onDismiss={noop} onUndismiss={noop} />
)

export const DataModelingWithDismissed: StoryFn = () => (
    <DataModelingHealthTable issues={DATA_MODELING_DISMISSED} onDismiss={noop} onUndismiss={noop} />
)

export const IngestionWarningsDefault: StoryFn = () => (
    <IngestionWarningTable issues={INGESTION_WARNING_ISSUES} onDismiss={noop} onUndismiss={noop} />
)

export const IngestionWarningsEmpty: StoryFn = () => (
    <IngestionWarningTable issues={[]} onDismiss={noop} onUndismiss={noop} />
)

export const PipelineDefault: StoryFn = () => (
    <PipelineHealthTable issues={PIPELINE_ISSUES} onDismiss={noop} onUndismiss={noop} />
)

export const PipelineEmpty: StoryFn = () => <PipelineHealthTable issues={[]} onDismiss={noop} onUndismiss={noop} />

export const WebAnalyticsAllChecks: StoryFn = () => (
    <WebAnalyticsHealthTable issues={WEB_ANALYTICS_ISSUES} onDismiss={noop} onUndismiss={noop} />
)

export const WebAnalyticsEmpty: StoryFn = () => (
    <WebAnalyticsHealthTable issues={[]} onDismiss={noop} onUndismiss={noop} />
)

export const SdkOutdatedDefault: StoryFn = () => <SdkOutdatedRenderer issue={SDK_OUTDATED_ISSUE} />

export const SdkOutdatedEmpty: StoryFn = () => <SdkOutdatedRenderer issue={SDK_OUTDATED_EMPTY_ISSUE} />

export const DetailHealthy: StoryFn = () => (
    <DataModelingDetailContent
        issues={[]}
        statusSummary={{ count: 0, worstSeverity: null, isHealthy: true }}
        isLoading={false}
        onDismiss={noop}
        onUndismiss={noop}
        onRefresh={noop}
        showDismissed={false}
        onSetShowDismissed={noop}
    />
)

export const DetailWithIssues: StoryFn = () => (
    <DataModelingDetailContent
        issues={DATA_MODELING_ISSUES}
        statusSummary={{ count: 3, worstSeverity: 'critical', isHealthy: false }}
        isLoading={false}
        onDismiss={noop}
        onUndismiss={noop}
        onRefresh={noop}
        showDismissed={false}
        onSetShowDismissed={noop}
    />
)
