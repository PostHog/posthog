import { Meta, StoryObj } from '@storybook/react'

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
    source_config: { serviceNames: ['checkout'], severityLevels: ['error'] },
    threshold_count: 100,
    threshold_operator: 'above',
    window_minutes: 5,
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
        },
    ],
}

const DISABLED_CONFIGURATION: PlatformAlertConfigurationApi = {
    ...CONFIGURATION,
    id: '0192a5b0-0000-7000-8000-000000000002',
    name: 'Daily signup volume below 10',
    enabled: false,
    threshold_operator: 'below',
    threshold_count: 10,
    window_minutes: 1440,
    recurrence_unit: 'day',
    anchor_time: '09:00',
    schedule_restriction: null,
    next_check_at: null,
    legacy_configuration_id: null,
    alerts: [],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/PlatformAlerts',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-10-05',
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
