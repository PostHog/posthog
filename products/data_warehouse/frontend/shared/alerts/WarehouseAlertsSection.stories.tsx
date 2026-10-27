import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import type { PlatformAlertConfigurationApi } from 'products/alerts_platform/frontend/generated/api.schemas'

import { WarehouseAlertsSection } from './WarehouseAlertsSection'

const STRIPE_SOURCE_ID = '0192a5b0-0000-7000-8000-00000000a001'

const DEFAULT_ALERT: PlatformAlertConfigurationApi = {
    id: '0192a5b0-0000-7000-8000-000000000001',
    name: 'Warehouse sync failures',
    enabled: true,
    source_kind: 'warehouse_source',
    source_config: { source_ids: [], group_by: 'source', email_project_members: true },
    check_interval_minutes: 5,
    recurrence_unit: null,
    anchor_time: null,
    evaluation_periods: 1,
    datapoints_to_alarm: 1,
    cooldown_minutes: 0,
    schedule_restriction: null,
    next_check_at: '2026-10-05T12:05:00Z',
    consecutive_failures: 0,
    legacy_configuration_id: null,
    grouping: { mode: 'by_result_labels', keys: ['source_id'], max_instances: 100, on_overflow: 'degrade_visible' },
    snooze_until: null,
    check_status: 'ok',
    overflowed_groups: 0,
    overflow_is_lower_bound: false,
    owner: 'platform',
    created_at: '2026-09-20T09:00:00Z',
    updated_at: '2026-10-01T09:00:00Z',
    alerts: [
        {
            id: '0192a5b0-0000-7000-8000-000000000101',
            grouping_key: STRIPE_SOURCE_ID,
            state: 'firing',
            firing_started_at: '2026-10-05T11:42:00Z',
            last_notified_at: '2026-10-05T11:42:05Z',
            snooze_until: null,
            labels: {},
        },
    ],
}

const PER_TABLE_ALERT: PlatformAlertConfigurationApi = {
    ...DEFAULT_ALERT,
    id: '0192a5b0-0000-7000-8000-000000000002',
    name: 'Stripe tables',
    source_config: { source_ids: [STRIPE_SOURCE_ID], group_by: 'schema', email_project_members: false },
    grouping: { ...DEFAULT_ALERT.grouping, keys: ['schema_id'] },
    alerts: [],
}

const meta: Meta = {
    title: 'Scenes-App/Data Warehouse/Alerts',
    component: WarehouseAlertsSection,
    parameters: { mockDate: '2026-10-05', viewMode: 'story' },
    render: () => {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/platform_alerts/': () => [
                    200,
                    { count: 2, next: null, previous: null, results: [DEFAULT_ALERT, PER_TABLE_ALERT] },
                ],
                '/api/environments/:team_id/external_data_sources/': () => [
                    200,
                    {
                        count: 1,
                        next: null,
                        previous: null,
                        results: [
                            {
                                id: STRIPE_SOURCE_ID,
                                source_type: 'Stripe',
                                prefix: 'billing',
                                access_method: 'warehouse',
                            },
                        ],
                    },
                ],
            },
        })

        return <WarehouseAlertsSection kind="warehouse_source" entry="sources_page" />
    },
}
export default meta

export const SourceAlerts: StoryObj = {}
