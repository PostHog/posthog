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
    /** Set when two rows ask for different values of one claim, so the policy could never match. */
    conflict?: string
}

export function conditionsFromRows(
    rows: WorkloadConditionRow[],
    provider: WorkloadProviderApi | null
): WorkloadConditionsResult {
    const labels = Object.fromEntries((provider?.condition_claims ?? []).map((claim) => [claim.name, claim.label]))
    const conditions: Record<string, string> = {}
    for (const row of rows) {
        const preset = provider?.condition_presets.find((candidate) => candidate.key === row.preset)
        const entries: [string, string][] = preset
            ? Object.entries(preset.conditions).map(([claim, template]) => [
                  claim,
                  template.replace(PRESET_VALUE, () => row.value.trim()),
              ])
            : row.claim
              ? [[row.claim, row.value.trim()]]
              : []
        for (const [claim, value] of entries) {
            // An empty value means the row isn't filled in yet, and the backend drops empty conditions.
            if (!value || (preset?.takes_value && !row.value.trim())) {
                continue
            }
            if (claim in conditions && conditions[claim] !== value) {
                return { conditions, conflict: `Two conditions ask for different values of ${labels[claim] ?? claim}.` }
            }
            conditions[claim] = value
        }
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
    const preset = provider?.condition_presets[0]
    return preset ? [rowForPreset(preset)] : []
}
