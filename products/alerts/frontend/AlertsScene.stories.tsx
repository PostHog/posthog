import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE, toPaginatedResponse } from '~/mocks/handlers'
import {
    AlertCalculationInterval,
    AlertConditionType,
    AlertState,
    InsightThresholdType,
} from '~/queries/schema/schema-general'

import type { LogsAlertConfigurationApi } from 'products/logs/frontend/generated/api.schemas'

import type { PlatformAlertConfigurationApi } from './generated/api.schemas'
import { AlertType } from './types'

const createdBy = {
    id: 1,
    uuid: '018f59f3-4f2f-7c89-b389-73b99b91f442',
    distinct_id: 'storybook-user',
    first_name: 'Hedge Hog',
    email: 'hedge@example.com',
    hedgehog_config: null,
}

const makeAlert = (overrides: Partial<AlertType>): AlertType =>
    ({
        id: 'alert-1',
        name: 'Weekly active users above 10,000',
        enabled: true,
        state: AlertState.NOT_FIRING,
        calculation_interval: AlertCalculationInterval.HOURLY,
        last_checked_at: '2026-07-16T16:45:00Z',
        last_notified_at: '2026-07-14T13:30:00Z',
        created_at: '2026-06-01T09:00:00Z',
        created_by: createdBy,
        subscribed_users: [createdBy],
        checks: [],
        config: {
            type: 'TrendsAlertConfig',
            series_index: 0,
            check_ongoing_interval: false,
        },
        threshold: {
            configuration: {
                type: InsightThresholdType.ABSOLUTE,
                bounds: { upper: 10000 },
            },
        },
        condition: { type: AlertConditionType.ABSOLUTE_VALUE },
        insight: {
            id: 101,
            short_id: 'weekly-active-users',
            name: 'Weekly active users',
            derived_name: 'Weekly active users',
        },
        ...overrides,
    }) as AlertType

const alerts: AlertType[] = [
    makeAlert({
        id: 'alert-firing',
        name: 'Checkout conversion below 40%',
        state: AlertState.FIRING,
        last_notified_at: '2026-07-16T16:45:00Z',
        insight: {
            id: 102,
            short_id: 'checkout-conversion',
            name: 'Checkout conversion',
            derived_name: 'Checkout conversion',
        } as AlertType['insight'],
    }),
    makeAlert({ id: 'alert-healthy' }),
    makeAlert({
        id: 'alert-disabled',
        name: 'Daily signups above 1,000',
        enabled: false,
        calculation_interval: AlertCalculationInterval.DAILY,
        last_notified_at: '',
        insight: {
            id: 103,
            short_id: 'daily-signups',
            name: 'Daily signups',
            derived_name: 'Daily signups',
        } as AlertType['insight'],
    }),
]

const logAlerts = [
    {
        id: '019abcde-1234-7000-8000-000000000101',
        name: 'Checkout errors',
        enabled: true,
        filters: { severityLevels: ['error'], serviceNames: ['checkout-api'] },
        threshold_count: 25,
        threshold_operator: 'above',
        window_minutes: 5,
        check_interval_minutes: 5,
        state: 'firing',
        evaluation_periods: 1,
        datapoints_to_alarm: 1,
        cooldown_minutes: 30,
        snooze_until: null,
        next_check_at: '2026-07-16T17:00:00Z',
        last_notified_at: '2026-07-16T16:55:00Z',
        last_checked_at: '2026-07-16T16:55:00Z',
        consecutive_failures: 0,
        last_error_message: null,
        state_timeline: [
            {
                start: '2026-07-15T17:00:00Z',
                end: '2026-07-16T16:30:00Z',
                state: 'not_firing',
                enabled: true,
            },
            {
                start: '2026-07-16T16:30:00Z',
                end: '2026-07-16T17:00:00Z',
                state: 'firing',
                enabled: true,
            },
        ],
        destination_types: ['slack'],
        first_enabled_at: '2026-07-10T15:00:00Z',
        created_at: '2026-07-10T14:45:00Z',
        created_by: createdBy,
        updated_at: '2026-07-16T16:55:00Z',
    },
    {
        id: '019abcde-1234-7000-8000-000000000102',
        name: 'No payment logs',
        enabled: true,
        filters: { serviceNames: ['payments-worker'] },
        threshold_count: 1,
        threshold_operator: 'below',
        window_minutes: 15,
        check_interval_minutes: 5,
        state: 'not_firing',
        evaluation_periods: 3,
        datapoints_to_alarm: 2,
        cooldown_minutes: 60,
        snooze_until: null,
        next_check_at: '2026-07-16T17:00:00Z',
        last_notified_at: null,
        last_checked_at: '2026-07-16T16:55:00Z',
        consecutive_failures: 0,
        last_error_message: null,
        state_timeline: [
            {
                start: '2026-07-15T17:00:00Z',
                end: '2026-07-16T17:00:00Z',
                state: 'not_firing',
                enabled: true,
            },
        ],
        destination_types: [],
        first_enabled_at: '2026-07-12T10:00:00Z',
        created_at: '2026-07-12T09:45:00Z',
        created_by: createdBy,
        updated_at: '2026-07-16T16:55:00Z',
    },
] satisfies LogsAlertConfigurationApi[]

const meta: Meta = {
    component: App,
    title: 'Products/Alerts/Alerts scene',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-07-16',
        pageUrl: `${urls.alerts()}?alert_type=insights`,
        testOptions: { viewport: { width: 1300, height: 900 } },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/alerts/': toPaginatedResponse(alerts),
                // The scene's setup gate counts both alert kinds over the project-scoped
                // API, so every story has to say whether the project has any alerts at all.
                '/api/projects/:team_id/alerts/': toPaginatedResponse(alerts),
            },
        }),
    ],
}

export default meta

type Story = StoryObj<{}>

export const InsightAlerts: Story = {}

// A project that alerts on logs but not on insights: the setup gate is satisfied, and
// the insights tab shows its own empty state.
export const EmptyState: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/alerts/': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/alerts/': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/logs/alerts/': [
                    200,
                    { count: logAlerts.length, next: null, previous: null, results: logAlerts },
                ],
            },
        }),
    ],
}

export const LogAlerts: Story = {
    parameters: {
        pageUrl: `${urls.alerts()}?alert_type=logs`,
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/logs/alerts/': [
                    200,
                    { count: logAlerts.length, next: null, previous: null, results: logAlerts },
                ],
            },
        }),
    ],
}

export const EmptyLogAlerts: Story = {
    parameters: {
        pageUrl: `${urls.alerts()}?alert_type=logs`,
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/logs/alerts/': EMPTY_PAGINATED_RESPONSE,
            },
        }),
    ],
}

const platformAlerts = [
    {
        id: '0199a1b2-0000-7000-8000-000000000001',
        name: 'Checkout errors',
        enabled: true,
        source_kind: 'logs',
        source_config: {},
        threshold_count: 50,
        threshold_operator: 'above',
        window_minutes: 5,
        check_interval_minutes: 1,
        evaluation_periods: 1,
        datapoints_to_alarm: 1,
        cooldown_minutes: 0,
        schedule_restriction: null,
        next_check_at: '2026-07-16T12:01:00Z',
        consecutive_failures: 0,
        created_at: '2026-07-10T09:00:00Z',
        updated_at: '2026-07-16T11:00:00Z',
        alerts: [
            {
                id: '0199a1b2-0000-7000-8000-000000000011',
                grouping_key: '',
                state: 'firing',
                firing_started_at: '2026-07-16T11:42:00Z',
                last_notified_at: null,
                snooze_until: null,
            },
        ],
    },
    {
        id: '0199a1b2-0000-7000-8000-000000000002',
        name: 'Payment service timeouts',
        enabled: false,
        source_kind: 'logs',
        source_config: {},
        threshold_count: 10,
        threshold_operator: 'above',
        window_minutes: 15,
        check_interval_minutes: 5,
        evaluation_periods: 3,
        datapoints_to_alarm: 2,
        cooldown_minutes: 30,
        schedule_restriction: null,
        next_check_at: null,
        consecutive_failures: 2,
        created_at: '2026-07-11T09:00:00Z',
        updated_at: '2026-07-15T08:00:00Z',
        alerts: [],
    },
] satisfies PlatformAlertConfigurationApi[]

export const PlatformAlerts: Story = {
    parameters: {
        pageUrl: `${urls.alerts()}?alert_type=platform`,
        featureFlags: [FEATURE_FLAGS.PLATFORM_ALERTS],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/platform_alerts/': toPaginatedResponse(platformAlerts),
            },
        }),
    ],
}
