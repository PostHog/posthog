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
    // The source product's own page for the alert, or null when the configuration cannot reach it.
    alertUrl: (configuration: PlatformAlertConfigurationApi) => string | null
}

function legacyAlertUrl(url: (legacyConfigurationId: string) => string): SourceKind['alertUrl'] {
    return ({ legacy_configuration_id }) => (legacy_configuration_id ? url(legacy_configuration_id) : null)
}

export const SOURCE_KINDS: Record<PlatformAlertConfigurationSourceKindEnumApi, SourceKind> = {
    [PlatformAlertConfigurationSourceKindEnumApi.Logs]: {
        label: 'Logs',
        alertUrl: legacyAlertUrl(urls.logsAlertDetail),
    },
    [PlatformAlertConfigurationSourceKindEnumApi.Insight]: {
        label: 'Insight',
        alertUrl: legacyAlertUrl(urls.alert),
    },
    // A warehouse alert has no page of its own, so it links to the page that lists what it watches.
    [PlatformAlertConfigurationSourceKindEnumApi.WarehouseSource]: {
        label: 'Warehouse source',
        alertUrl: () => urls.sources(),
    },
    [PlatformAlertConfigurationSourceKindEnumApi.WarehouseDestination]: {
        label: 'Warehouse destination',
        alertUrl: () => urls.warehouseDestinations(),
    },
    [PlatformAlertConfigurationSourceKindEnumApi.Metrics]: {
        label: 'Metrics',
        alertUrl: () => urls.metrics(),
    },
}

export function sourceAlertUrl(configuration: PlatformAlertConfigurationApi): string | null {
    return SOURCE_KINDS[configuration.source_kind].alertUrl(configuration)
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

// Each source keeps its bound under `source_config.condition` in its own shape. Only the logs shape
// reads as one line, so other sources fall back to the raw settings on the detail page.
export function describeCondition(configuration: PlatformAlertConfigurationApi): string {
    const condition = configuration.source_config.condition
    if (typeof condition !== 'object' || condition === null) {
        return 'See source settings'
    }
    const { threshold_operator, threshold_count, window_minutes } = condition as Record<string, unknown>
    if (typeof threshold_count !== 'number' || typeof window_minutes !== 'number') {
        return 'See source settings'
    }
    const operator = threshold_operator === 'below' ? 'Below' : 'Above'
    return `${operator} ${threshold_count} in ${window_minutes} min`
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
