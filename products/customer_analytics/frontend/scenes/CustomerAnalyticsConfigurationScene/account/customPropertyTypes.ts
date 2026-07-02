import { humanFriendlyCurrency, humanFriendlyLargeNumber, humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import type {
    CustomPropertyDefinitionApi,
    CustomPropertyDisplayTypeEnumApi,
    CustomPropertySourceApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

// The backend stores the granular display type directly, so the form value maps 1:1 to the API.
// This file holds only the UI metadata (label + whether the big-number switch applies).
export interface DisplayTypeOption {
    value: CustomPropertyDisplayTypeEnumApi
    label: string
    isNumeric: boolean
}

export const DISPLAY_TYPE_OPTIONS: DisplayTypeOption[] = [
    { value: 'text', label: 'Text', isNumeric: false },
    { value: 'number', label: 'Number', isNumeric: true },
    { value: 'currency', label: 'Currency', isNumeric: true },
    { value: 'percent', label: 'Percent', isNumeric: true },
    { value: 'date', label: 'Date', isNumeric: false },
    { value: 'datetime', label: 'Date & time', isNumeric: false },
    { value: 'boolean', label: 'True / false', isNumeric: false },
]

export function labelForDisplayType(displayType: CustomPropertyDisplayTypeEnumApi): string {
    return DISPLAY_TYPE_OPTIONS.find((option) => option.value === displayType)?.label ?? displayType
}

// Drives the big-number switch: it's only shown — and only meaningful in the payload — for numeric types.
export function isNumericDisplayType(displayType: CustomPropertyDisplayTypeEnumApi): boolean {
    return DISPLAY_TYPE_OPTIONS.find((option) => option.value === displayType)?.isNumeric ?? false
}

const EMPTY_VALUE = '—'

// Formats a custom property value (always a string off the JSON column) for display per its
// definition's display type. Date/datetime/boolean are handled by the cell (TZLabel / icon),
// so this returns the raw string for them and focuses on the numeric formats.
export function formatCustomPropertyValue(
    raw: string | null | undefined,
    definition: Pick<CustomPropertyDefinitionApi, 'display_type' | 'is_big_number'>
): string {
    if (raw === null || raw === undefined || raw === '') {
        return EMPTY_VALUE
    }
    const numeric = Number(raw)
    const isNumber = Number.isFinite(numeric)
    switch (definition.display_type) {
        case 'currency':
            return isNumber ? humanFriendlyCurrency(numeric) : raw
        // Percent values are stored as fractions (0.5 → 50%), matching how the backend coerces them
        // (see test_custom_property_values.py: a `percent` definition stores 0.5). percentage() multiplies by 100.
        case 'percent':
            return isNumber ? percentage(numeric) : raw
        case 'number':
            if (!isNumber) {
                return raw
            }
            return definition.is_big_number ? humanFriendlyLargeNumber(numeric) : humanFriendlyNumber(numeric)
        default:
            return raw
    }
}

export type SourceSyncStatusLevel = 'synced' | 'error' | 'disabled' | 'pending'

export interface SourceSyncStatus {
    level: SourceSyncStatusLevel
    label: string
    tooltip?: string
}

// Derives the displayed sync state from the source's stored fields. The backend records only
// `is_enabled` + `last_sync_error` + `last_synced_at`; status is computed, not stored.
export function sourceSyncStatus(source: CustomPropertySourceApi): SourceSyncStatus {
    if (!source.is_enabled) {
        return {
            level: 'disabled',
            label: 'Disabled',
            tooltip: source.last_sync_error ?? 'Syncing is turned off for this source.',
        }
    }
    if (source.last_sync_error) {
        return { level: 'error', label: 'Sync error', tooltip: source.last_sync_error }
    }
    if (!source.last_synced_at) {
        return { level: 'pending', label: 'Awaiting first sync' }
    }
    return { level: 'synced', label: 'Synced' }
}
