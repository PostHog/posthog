import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { useEffect, useRef } from 'react'

import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { DataQualityOverview } from './DataQualityOverview'

const grantWarehouseAccess: Decorator = function GrantWarehouseAccess(Story): JSX.Element {
    const appContext = window.POSTHOG_APP_CONTEXT
    const original = useRef(appContext ? { appContext, access: appContext.resource_access_control } : null)
    if (appContext) {
        appContext.resource_access_control = {
            ...appContext.resource_access_control,
            [AccessControlResourceType.WarehouseObjects]: AccessControlLevel.Editor,
        }
    }
    useEffect(
        () => () => {
            if (original.current) {
                original.current.appContext.resource_access_control = original.current.access
            }
        },
        [appContext]
    )
    return <Story />
}

const LONG_SUBJECT_NAME = 'monthly_revenue_summary_by_region_and_channel_v2'

const checks = [
    {
        id: 'check-1',
        name: 'order_id is never null',
        check_type: 'not_null',
        column_name: 'order_id',
        severity: 'error',
        enabled: true,
        subject_type: 'view',
        subject_uuid: 'view-long-name',
        subject_name: LONG_SUBJECT_NAME,
        subject_node_id: 'node-long-name',
        last_status: 'failed',
        last_run_at: '2026-09-14T22:00:00Z',
    },
    {
        id: 'check-2',
        name: 'revenue rows arrive daily',
        check_type: 'freshness',
        column_name: '',
        severity: 'warn',
        enabled: true,
        subject_type: 'view',
        subject_uuid: 'view-long-name',
        subject_name: LONG_SUBJECT_NAME,
        subject_node_id: 'node-long-name',
        last_status: 'passed',
        last_run_at: '2026-09-14T22:00:00Z',
    },
    {
        id: 'check-3',
        name: 'customer_id is unique',
        check_type: 'unique',
        column_name: 'customer_id',
        severity: 'error',
        enabled: true,
        subject_type: 'table',
        subject_uuid: 'table-customers',
        subject_name: 'customers',
        last_status: 'passed',
        last_run_at: '2026-09-14T21:30:00Z',
    },
    {
        id: 'check-4',
        name: 'signup conversion stays under 100%',
        check_type: 'custom_sql',
        column_name: '',
        severity: 'error',
        enabled: true,
        subject_type: 'metric',
        subject_uuid: 'metric-signup-conversion',
        subject_name: 'signup_conversion',
        subject_metric_name: 'signup_conversion',
        last_status: null,
        last_run_at: null,
    },
]

const health = [
    {
        subject_type: 'view',
        subject_uuid: 'view-long-name',
        health: 'failing',
        checks_total: 2,
        checks_failing: 1,
    },
    {
        subject_type: 'table',
        subject_uuid: 'table-customers',
        health: 'healthy',
        checks_total: 1,
        checks_failing: 0,
    },
    {
        subject_type: 'metric',
        subject_uuid: 'metric-signup-conversion',
        health: 'unknown',
        checks_total: 1,
        checks_failing: 0,
    },
]

function mocks(overviewChecks: unknown[], subjectHealth: unknown[]): Record<string, unknown> {
    return {
        get: {
            '/api/projects/:team_id/data_quality_checks/': {
                results: overviewChecks,
                count: overviewChecks.length,
            },
            '/api/projects/:team_id/data_quality_checks/health/': subjectHealth,
            '/api/projects/:team_id/data_warehouse/data_quality_gate/': { gate_materialization_on_checks: true },
        },
    }
}

const narrowDecorators: Decorator[] = [
    (Story) => (
        <div className="@container/main-content w-128 max-w-full">
            <Story />
        </div>
    ),
]

const meta: Meta<typeof DataQualityOverview> = {
    title: 'Products/Data quality/Overview',
    component: DataQualityOverview,
    decorators: [
        grantWarehouseAccess,
        (Story) => (
            <div className="@container/main-content">
                <Story />
            </div>
        ),
        mswDecorator({}),
    ],
    parameters: {
        pageUrl: urls.models('data-quality'),
        mockDate: '2026-09-15',
        msw: { mocks: mocks(checks, health) },
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof DataQualityOverview>

export const Default: Story = {}

export const Narrow: Story = { decorators: narrowDecorators }

export const Empty: Story = {
    parameters: { msw: { mocks: mocks([], []) } },
}

export const NarrowEmpty: Story = {
    ...Empty,
    decorators: narrowDecorators,
}
