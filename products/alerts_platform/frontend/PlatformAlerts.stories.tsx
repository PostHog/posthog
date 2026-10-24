import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { PlatformAlertConfigurationApi } from './generated/api.schemas'

const CONFIGURATION: PlatformAlertConfigurationApi = {
    id: '0192a5b0-0000-7000-8000-000000000001',
    name: 'Checkout errors above 100',
    enabled: true,
    source_kind: 'logs',
    source_config: {
        filters: { serviceNames: ['checkout'], severityLevels: ['error'] },
        condition: { threshold_count: 100, threshold_operator: 'above', window_minutes: 5 },
    },
    check_interval_minutes: 1,
    recurrence_unit: null,
    anchor_time: null,
    evaluation_periods: 3,
    datapoints_to_alarm: 2,
    cooldown_minutes: 30,
    schedule_restriction: { blocked_windows: [{ start: '22:00', end: '07:00' }] },
    next_check_at: '2026-10-05T12:01:00Z',
    consecutive_failures: 0,
    legacy_configuration_id: '0192a5b0-0000-7000-8000-0000000000aa',
    grouping: { mode: 'single', keys: [], max_instances: 100, on_overflow: 'degrade_visible' },
    snooze_until: null,
    check_status: 'ok',
    overflowed_groups: 0,
    overflow_is_lower_bound: false,
    owner: 'source',
    created_at: '2026-09-20T09:00:00Z',
    updated_at: '2026-10-01T09:00:00Z',
    alerts: [
        {
            id: '0192a5b0-0000-7000-8000-000000000101',
            grouping_key: '',
            state: 'firing',
            firing_started_at: '2026-10-05T11:42:00Z',
            last_notified_at: '2026-10-05T11:42:05Z',
            snooze_until: null,
            labels: {},
        },
    ],
}

const DISABLED_CONFIGURATION: PlatformAlertConfigurationApi = {
    ...CONFIGURATION,
    id: '0192a5b0-0000-7000-8000-000000000002',
    name: 'Daily signup volume below 10',
    enabled: false,
    source_kind: 'insight',
    source_config: {
        insight_id: 42,
        condition: {
            threshold: { type: 'absolute', bounds: { lower: 10 } },
            comparison: { type: 'absolute_value' },
        },
    },
    recurrence_unit: 'day',
    anchor_time: '09:00',
    schedule_restriction: null,
    next_check_at: null,
    legacy_configuration_id: null,
    alerts: [],
}

const GROUPED_CONFIGURATION: PlatformAlertConfigurationApi = {
    ...CONFIGURATION,
    id: '0192a5b0-0000-7000-8000-000000000003',
    name: 'Errors per service above 50',
    legacy_configuration_id: null,
    owner: 'platform',
    grouping: {
        mode: 'by_result_labels',
        keys: ['service_name', 'severity_text'],
        max_instances: 3,
        on_overflow: 'degrade_visible',
    },
    overflowed_groups: 3,
    overflow_is_lower_bound: true,
    alerts: [
        {
            id: '0192a5b0-0000-7000-8000-000000000301',
            grouping_key: '{"service_name":"checkout","severity_text":"error"}',
            state: 'firing',
            firing_started_at: '2026-10-05T11:42:00Z',
            last_notified_at: '2026-10-05T11:42:05Z',
            snooze_until: null,
            labels: { service_name: 'checkout', severity_text: 'error' },
        },
        {
            id: '0192a5b0-0000-7000-8000-000000000302',
            grouping_key: '{"service_name":"payments-api","severity_text":"error"}',
            state: 'snoozed',
            firing_started_at: '2026-10-05T10:15:00Z',
            last_notified_at: '2026-10-05T10:15:04Z',
            snooze_until: '2026-10-06T10:00:00Z',
            labels: { service_name: 'payments-api', severity_text: 'error' },
        },
        {
            id: '0192a5b0-0000-7000-8000-000000000303',
            grouping_key: 'sha256:5f0c3e5b9a8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1e0d9c8b7a6f5e4d3c2b',
            state: 'not_firing',
            firing_started_at: null,
            last_notified_at: null,
            snooze_until: null,
            labels: {
                service_name: 'recommendations-worker-with-a-very-long-service-name-from-kubernetes',
                severity_text: 'warn',
            },
        },
    ],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/PlatformAlerts',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-10-05T12:00:00Z',
        featureFlags: [FEATURE_FLAGS.PLATFORM_ALERTS],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/platform_alerts/': {
                    count: 2,
                    next: null,
                    previous: null,
                    results: [CONFIGURATION, DISABLED_CONFIGURATION],
                },
                [`/api/projects/:team_id/platform_alerts/${CONFIGURATION.id}/`]: CONFIGURATION,
                [`/api/projects/:team_id/platform_alerts/${GROUPED_CONFIGURATION.id}/`]: GROUPED_CONFIGURATION,
            },
            post: {
                [`/api/projects/:team_id/platform_alerts/${GROUPED_CONFIGURATION.id}/snooze_group/`]:
                    GROUPED_CONFIGURATION.alerts[0],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const List: Story = {
    parameters: { pageUrl: urls.platformAlerts() },
}

export const Detail: Story = {
    parameters: { pageUrl: urls.platformAlert(CONFIGURATION.id) },
}

export const DetailGrouped: Story = {
    parameters: { pageUrl: urls.platformAlert(GROUPED_CONFIGURATION.id) },
}

export const DetailGroupedSnoozeMenuOpen: Story = {
    parameters: { pageUrl: urls.platformAlert(GROUPED_CONFIGURATION.id) },
    // Opens the menu of the snoozed group, so Unsnooze shows. A native click rather than userEvent:
    // userEvent wraps the event in `act`, which throws in the production React build the visual
    // regression runner uses.
    play: async ({ canvasElement }) => {
        await within(canvasElement).findAllByText('Snoozed')
        const triggers = canvasElement.querySelectorAll<HTMLElement>('[data-attr="platform-alert-group-snooze-menu"]')
        Array.from(triggers)
            .find((trigger) => trigger.textContent === 'Snoozed')
            ?.click()
        await within(document.body).findByText('Unsnooze')
    },
}
