import {
    BillingAlertConfigurationStateEnumApi as PlatformAlertStateApi,
    CalendarUnitEnumApi,
    PlatformAlertApi,
    PlatformAlertConfigurationApi,
} from './generated/api.schemas'
import { PlatformAlertConfigurationStatus, configurationStatus, describeSchedule } from './platformAlertFormat'

function makeConfiguration(overrides: Partial<PlatformAlertConfigurationApi> = {}): PlatformAlertConfigurationApi {
    return {
        id: 'configuration-id',
        name: 'Error spike',
        enabled: true,
        source_kind: 'logs',
        source_config: {},
        threshold_count: 100,
        threshold_operator: 'above',
        window_minutes: 5,
        check_interval_minutes: 1,
        recurrence_unit: null,
        anchor_time: null,
        evaluation_periods: 1,
        datapoints_to_alarm: 1,
        cooldown_minutes: 0,
        schedule_restriction: null,
        next_check_at: null,
        consecutive_failures: 0,
        legacy_configuration_id: null,
        created_at: '2026-10-01T00:00:00Z',
        updated_at: '2026-10-01T00:00:00Z',
        alerts: [],
        ...overrides,
    }
}

function makeAlert(state: PlatformAlertStateApi): PlatformAlertApi {
    return {
        id: `alert-${state}`,
        grouping_key: state,
        state,
        firing_started_at: null,
        last_notified_at: null,
        snooze_until: null,
    }
}

describe('platformAlertFormat', () => {
    test.each<[string, Partial<PlatformAlertConfigurationApi>, PlatformAlertConfigurationStatus]>([
        ['no groups yet', {}, 'not_checked'],
        [
            'disabled hides group state',
            { enabled: false, alerts: [makeAlert(PlatformAlertStateApi.Firing)] },
            'disabled',
        ],
        [
            'one firing group outranks healthy ones',
            {
                alerts: [
                    makeAlert(PlatformAlertStateApi.NotFiring),
                    makeAlert(PlatformAlertStateApi.Firing),
                    makeAlert(PlatformAlertStateApi.Snoozed),
                ],
            },
            'firing',
        ],
        [
            'broken outranks firing',
            { alerts: [makeAlert(PlatformAlertStateApi.Firing), makeAlert(PlatformAlertStateApi.Broken)] },
            'broken',
        ],
    ])('configurationStatus: %s', (_, overrides, expected) => {
        expect(configurationStatus(makeConfiguration(overrides))).toEqual(expected)
    })

    test.each<[string, Partial<PlatformAlertConfigurationApi>, string]>([
        ['interval', { check_interval_minutes: 15 }, 'Every 15 min'],
        [
            'calendar unit ignores the interval',
            { check_interval_minutes: 15, recurrence_unit: CalendarUnitEnumApi.Week },
            'Every week',
        ],
        [
            'calendar unit with anchor',
            { recurrence_unit: CalendarUnitEnumApi.Day, anchor_time: '09:00' },
            'Every day at 09:00',
        ],
    ])('describeSchedule: %s', (_, overrides, expected) => {
        expect(describeSchedule(makeConfiguration(overrides))).toEqual(expected)
    })
})
