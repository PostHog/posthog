import { DataColorToken } from 'lib/colors'
import { humanFriendlyCurrency, humanFriendlyLargeNumber, humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import type {
    CustomPropertyDefinitionApi,
    CustomPropertyDisplayTypeEnumApi,
    CustomPropertyOptionApi,
    CustomPropertySourceApi,
    CustomPropertySyncRunApi,
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
    { value: 'select', label: 'Select', isNumeric: false },
]

// Keep in sync with CUSTOM_PROPERTY_OPTION_COLORS in the backend's constants.py.
export const OPTION_COLOR_TOKENS: DataColorToken[] = Array.from(
    { length: 10 },
    (_, index) => `preset-${index + 1}` as DataColorToken
)

// New options get a client-side id for a stable React key; the server mints the real id, so
// these are stripped from the payload on save.
export const NEW_OPTION_ID_PREFIX = 'new-'

export function optionLabelError(options: CustomPropertyOptionApi[], index: number): string | undefined {
    const label = options[index].label.trim()
    if (!label) {
        return 'Please enter a label.'
    }
    if (options.slice(0, index).some((option) => option.label.trim() === label)) {
        return 'Duplicate option label.'
    }
    return undefined
}

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

export interface RunOutcomeNote {
    label: string
    tooltip: string
}

// A completed run that updated nobody is normal, not a failure: a sync only stages rows the
// warehouse import actually changed, and the snapshot diff then drops rows whose mapped values
// already match what was last sent. Both look identical in the counts (all zeros), so name which
// one happened rather than leaving a row of zeros to be read as a broken sync.
export function runOutcomeNote(run: CustomPropertySyncRunApi, entityPlural: string): RunOutcomeNote | null {
    if (run.status !== 'completed' || run.produced > 0) {
        return null
    }
    if (run.rows_read === 0) {
        return {
            label: 'no new rows',
            tooltip: `This run read no warehouse rows, so there was nothing to map onto ${entityPlural}.`,
        }
    }
    if (run.changed === 0) {
        return {
            label: 'no changes',
            tooltip: `All ${humanFriendlyNumber(run.rows_read)} rows this sync read already hold the values last sent, so nothing needed updating.`,
        }
    }
    if (run.existing === 0) {
        return {
            label: `no matching ${entityPlural}`,
            tooltip: `${humanFriendlyNumber(run.changed)} rows changed, but none of their key column values matched an existing ${entityPlural === 'people' ? 'person' : 'group'}.`,
        }
    }
    return null
}
