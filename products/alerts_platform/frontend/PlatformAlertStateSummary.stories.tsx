import { Meta, StoryObj } from '@storybook/react'

import { PlatformAlertApi, PlatformAlertConfigurationApi } from './generated/api.schemas'
import { PlatformAlertStateSummary } from './PlatformAlertStateSummary'

function group(state: PlatformAlertApi['state'], index: number): PlatformAlertApi {
    return {
        id: `0192a5b0-0000-7000-8000-00000000010${index}`,
        grouping_key: `{"service_name":"service-${index}"}`,
        state,
        firing_started_at: null,
        last_notified_at: null,
        snooze_until: null,
        labels: { service_name: `service-${index}` },
    }
}

function configuration(
    name: string,
    states: PlatformAlertApi['state'][],
    enabled: boolean = true
): PlatformAlertConfigurationApi {
    return {
        id: name,
        name,
        enabled,
        labels: {},
        annotations: {},
        created_by: null,
        last_checked_at: null,
        last_error_message: null,
        state_timeline: [],
        destination_types: [],
        source_kind: 'logs',
        source_config: {},
        check_interval_minutes: 5,
        recurrence_unit: null,
        anchor_time: null,
        evaluation_periods: 1,
        datapoints_to_alarm: 1,
        cooldown_minutes: 0,
        schedule_restriction: null,
        next_check_at: null,
        consecutive_failures: 0,
        legacy_configuration_id: null,
        grouping: { mode: 'single', keys: [], max_instances: 100, on_overflow: 'degrade_visible' },
        snooze_until: null,
        check_status: 'ok',
        overflowed_groups: 0,
        overflow_is_lower_bound: false,
        owner: 'platform',
        created_at: '2026-10-01T00:00:00Z',
        updated_at: '2026-10-01T00:00:00Z',
        alerts: states.map(group),
    }
}

const CONFIGURATIONS: PlatformAlertConfigurationApi[] = [
    configuration('One group, OK', ['not_firing']),
    configuration('One group, firing', ['firing']),
    configuration('One group, errored', ['errored']),
    configuration('One group, broken', ['broken']),
    configuration('One group, snoozed', ['snoozed']),
    configuration('Not checked yet', []),
    configuration('Disabled', ['firing'], false),
    configuration('Many groups, every state', [
        'broken',
        'errored',
        'firing',
        'firing',
        'firing',
        'snoozed',
        'not_firing',
        'not_firing',
    ]),
]

const meta: Meta<typeof PlatformAlertStateSummary> = {
    title: 'Scenes-App/PlatformAlerts/State summary',
    component: PlatformAlertStateSummary,
    parameters: {
        layout: 'padded',
    },
}
export default meta

type Story = StoryObj<typeof PlatformAlertStateSummary>

export const AllStates: Story = {
    render: () => (
        <div className="flex flex-col gap-2">
            {CONFIGURATIONS.map((item) => (
                <div key={item.id} className="flex items-center gap-4">
                    <span className="w-60 text-muted">{item.name}</span>
                    <PlatformAlertStateSummary configuration={item} />
                </div>
            ))}
        </div>
    ),
}

export const WrapsWhenNarrow: Story = {
    render: () => (
        <div className="w-40 border border-primary p-2">
            <PlatformAlertStateSummary configuration={CONFIGURATIONS[CONFIGURATIONS.length - 1]} />
        </div>
    ),
}
