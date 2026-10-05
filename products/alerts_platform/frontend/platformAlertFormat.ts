import { urls } from 'scenes/urls'

import {
    BillingAlertConfigurationStateEnumApi as PlatformAlertStateApi,
    CalendarUnitEnumApi,
    PlatformAlertConfigurationApi,
    PlatformAlertConfigurationSourceKindEnumApi,
} from './generated/api.schemas'

export type PlatformAlertConfigurationStatus = PlatformAlertStateApi | 'disabled' | 'not_checked'

interface SourceKind {
    label: string
    // The source product's own page for the alert, reached through the legacy configuration id.
    alertUrl?: (legacyConfigurationId: string) => string
}

export const SOURCE_KINDS: Record<PlatformAlertConfigurationSourceKindEnumApi, SourceKind> = {
    [PlatformAlertConfigurationSourceKindEnumApi.Logs]: {
        label: 'Logs',
        alertUrl: (legacyConfigurationId) => urls.logsAlertDetail(legacyConfigurationId),
    },
}

export function sourceAlertUrl(configuration: PlatformAlertConfigurationApi): string | null {
    const { alertUrl } = SOURCE_KINDS[configuration.source_kind]
    return alertUrl && configuration.legacy_configuration_id ? alertUrl(configuration.legacy_configuration_id) : null
}

// Most urgent first, so a configuration shows the state that needs attention.
const STATE_PRIORITY: PlatformAlertStateApi[] = [
    PlatformAlertStateApi.Broken,
    PlatformAlertStateApi.Errored,
    PlatformAlertStateApi.Firing,
    PlatformAlertStateApi.Snoozed,
    PlatformAlertStateApi.NotFiring,
]

const CALENDAR_UNIT_LABELS: Record<CalendarUnitEnumApi, string> = {
    [CalendarUnitEnumApi.Day]: 'day',
    [CalendarUnitEnumApi.Week]: 'week',
    [CalendarUnitEnumApi.Month]: 'month',
}

export function configurationStatus(configuration: PlatformAlertConfigurationApi): PlatformAlertConfigurationStatus {
    if (!configuration.enabled) {
        return 'disabled'
    }
    const states = new Set(configuration.alerts.map((alert) => alert.state))
    return STATE_PRIORITY.find((state) => states.has(state)) ?? 'not_checked'
}

export function describeCondition(configuration: PlatformAlertConfigurationApi): string {
    const operator = configuration.threshold_operator === 'below' ? 'Below' : 'Above'
    return `${operator} ${configuration.threshold_count} in ${configuration.window_minutes} min`
}

export function describeSchedule(configuration: PlatformAlertConfigurationApi): string {
    if (configuration.recurrence_unit === null) {
        return `Every ${configuration.check_interval_minutes} min`
    }
    const unit = CALENDAR_UNIT_LABELS[configuration.recurrence_unit]
    return configuration.anchor_time ? `Every ${unit} at ${configuration.anchor_time}` : `Every ${unit}`
}

export function describeQuietHours(configuration: PlatformAlertConfigurationApi): string {
    const windows = configuration.schedule_restriction?.blocked_windows ?? []
    return windows.length ? windows.map((window) => `${window.start}-${window.end}`).join(', ') : 'None'
}
