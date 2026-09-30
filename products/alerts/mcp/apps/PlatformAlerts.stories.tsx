import type { Meta, StoryObj } from '@storybook/react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'

import { type PlatformAlertData, PlatformAlertListView, PlatformAlertView } from './index'

const meta: Meta = {
    title: 'MCP Apps/Platform alerts',
    decorators: [McpThemeDecorator],
    parameters: {
        testOptions: {
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

const baseAlert = {
    enabled: true,
    source_kind: 'logs',
    threshold_count: 50,
    threshold_operator: 'above',
    window_minutes: 5,
    check_interval_minutes: 1,
    evaluation_periods: 3,
    datapoints_to_alarm: 2,
    next_check_at: '2026-09-30T13:15:00Z',
    consecutive_failures: 0,
}

const groupedFiringAlert: PlatformAlertData = {
    ...baseAlert,
    id: '0199a1b2-0000-7000-8000-000000000001',
    name: 'API 5xx by service',
    alerts: [
        {
            id: '0199a1b2-0000-7000-8000-000000000011',
            grouping_key: 'checkout-api',
            state: 'firing',
            firing_started_at: '2026-09-30T13:02:00Z',
            last_notified_at: '2026-09-30T13:02:00Z',
            snooze_until: null,
        },
        {
            id: '0199a1b2-0000-7000-8000-000000000012',
            grouping_key: 'payments-api',
            state: 'firing',
            firing_started_at: '2026-09-30T13:05:00Z',
            last_notified_at: null,
            snooze_until: null,
        },
        {
            id: '0199a1b2-0000-7000-8000-000000000013',
            grouping_key: 'search-api',
            state: 'not_firing',
            firing_started_at: null,
            last_notified_at: '2026-09-29T09:14:00Z',
            snooze_until: null,
        },
    ],
}

const erroredAlert: PlatformAlertData = {
    ...baseAlert,
    id: '0199a1b2-0000-7000-8000-000000000002',
    name: 'Payment webhook timeouts',
    check_interval_minutes: 5,
    consecutive_failures: 3,
    alerts: [
        {
            id: '0199a1b2-0000-7000-8000-000000000021',
            grouping_key: '',
            state: 'errored',
            firing_started_at: null,
            last_notified_at: null,
            snooze_until: null,
        },
    ],
}

const disabledAlert: PlatformAlertData = {
    ...baseAlert,
    id: '0199a1b2-0000-7000-8000-000000000003',
    name: 'Nightly export failures',
    enabled: false,
    check_interval_minutes: 60,
    next_check_at: null,
    alerts: [],
}

export const List: Story = {
    render: () => (
        <PlatformAlertListView
            data={{ results: [groupedFiringAlert, erroredAlert, disabledAlert] }}
            onPlatformAlertClick={async (alert) => alert}
        />
    ),
}

export const EmptyList: Story = {
    render: () => <PlatformAlertListView data={{ results: [] }} />,
}

export const GroupedDetail: Story = {
    render: () => <PlatformAlertView data={groupedFiringAlert} />,
}

export const ErroredDetail: Story = {
    render: () => <PlatformAlertView data={erroredAlert} />,
}
