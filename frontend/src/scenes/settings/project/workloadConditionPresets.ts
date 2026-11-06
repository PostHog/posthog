import type { WorkloadProviderApi } from '~/generated/core/api.schemas'

// Stands for what a person types into a preset's field, as the backend registry writes it.
const PRESET_VALUE = '{value}'

/** A preset key from the provider, or this for one claim set by hand. */
export const CUSTOM_CONDITION = 'custom'

export interface WorkloadConditionRow {
    preset: string
    /** What the person typed: the preset's value, or the custom claim's value. */
    value: string
    claim?: string
}

export interface WorkloadConditionsResult {
    conditions: Record<string, string>
    conflict?: string
}

// The claims a row sets. A row whose field is still empty sets none, and the backend drops empty values anyway.
function rowConditions(row: WorkloadConditionRow, provider: WorkloadProviderApi | null): [string, string][] {
    const value = row.value.trim()
    const preset = provider?.condition_presets.find((candidate) => candidate.key === row.preset)
    if (preset) {
        return preset.takes_value && !value
            ? []
            : Object.entries(preset.conditions).map(([claim, template]) => [
                  claim,
                  template.replace(PRESET_VALUE, () => value),
              ])
    }
    return row.claim && value ? [[row.claim, value]] : []
}

export function conditionsFromRows(
    rows: WorkloadConditionRow[],
    provider: WorkloadProviderApi | null
): WorkloadConditionsResult {
    const conditions: Record<string, string> = {}
    for (const [claim, value] of rows.flatMap((row) => rowConditions(row, provider))) {
        if (claim in conditions && conditions[claim] !== value) {
            const label = provider?.condition_claims.find((candidate) => candidate.name === claim)?.label ?? claim
            return { conditions, conflict: `Two conditions ask for different values of ${label}.` }
        }
        conditions[claim] = value
    }
    return { conditions }
}

function presetValue(template: string, value: string): string | undefined {
    const at = template.indexOf(PRESET_VALUE)
    if (at === -1) {
        return template === value ? '' : undefined
    }
    const prefix = template.slice(0, at)
    const suffix = template.slice(at + PRESET_VALUE.length)
    const matches = value.startsWith(prefix) && value.endsWith(suffix) && value.length > prefix.length + suffix.length
    return matches ? value.slice(prefix.length, value.length - suffix.length) : undefined
}

/** The rows that show a stored policy's conditions, as presets where they fit and custom rows otherwise. */
export function rowsFromConditions(
    conditions: Record<string, string>,
    provider: WorkloadProviderApi | null
): WorkloadConditionRow[] {
    const left = { ...conditions }
    const rows: WorkloadConditionRow[] = []
    for (const preset of provider?.condition_presets ?? []) {
        const values = Object.entries(preset.conditions).map(([claim, template]) =>
            claim in left ? presetValue(template, left[claim]) : undefined
        )
        const typed = values.filter((value) => value !== '')
        if (values.some((value) => value === undefined) || new Set(typed).size > 1) {
            continue
        }
        rows.push({ preset: preset.key, value: typed[0] ?? '' })
        for (const claim of Object.keys(preset.conditions)) {
            delete left[claim]
        }
    }
    for (const [claim, value] of Object.entries(left)) {
        rows.push({ preset: CUSTOM_CONDITION, claim, value })
    }
    return rows
}

export function rowForPreset(preset: WorkloadProviderApi['condition_presets'][number]): WorkloadConditionRow {
    return { preset: preset.key, value: preset.default_value }
}

export function defaultConditionRows(provider: WorkloadProviderApi | null): WorkloadConditionRow[] {
    const presets = provider?.condition_presets ?? []
    const required = new Set(provider?.required_condition_claims ?? [])
    const covering = presets.filter((preset) => Object.keys(preset.conditions).some((claim) => required.has(claim)))
    const first = presets.find((preset) => !covering.includes(preset))
    return [...covering, ...(first ? [first] : [])].map(rowForPreset)
}

export function conditionsError(
    conditions: Record<string, string>,
    provider: WorkloadProviderApi | null,
    conflict?: string
): string | undefined {
    if (conflict) {
        return conflict
    }
    const required = provider?.required_condition_claims ?? []
    const missing = required
        .filter((claim) => !conditions[claim])
        .map((claim) => provider?.condition_claims.find((candidate) => candidate.name === claim)?.label ?? claim)
    if (missing.length) {
        return `Set these conditions: ${missing.join(', ')}`
    }
    // The required claims pin the account, not the runs, so a policy needs another condition too.
    const runClaims = (provider?.condition_claims ?? []).filter((claim) => !required.includes(claim.name))
    if (runClaims.length && !runClaims.some((claim) => conditions[claim.name])) {
        return 'Choose which runs can get a token'
    }
    return undefined
}
