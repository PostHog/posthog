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

interface WorkloadConditionsResult {
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
            return {
                conditions,
                conflict: `Two conditions ask for different values of ${claimLabel(provider, claim)}.`,
            }
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
    return (provider?.default_presets ?? [])
        .flatMap((key) => presets.filter((preset) => preset.key === key))
        .map(rowForPreset)
}

function claimLabel(provider: WorkloadProviderApi | null, claim: string): string {
    return provider?.condition_claims.find((candidate) => candidate.name === claim)?.label ?? claim
}

function companionError(conditions: Record<string, string>, provider: WorkloadProviderApi | null): string | undefined {
    for (const rule of provider?.condition_companions ?? []) {
        const alone = rule.claims.find((claim) => conditions[claim])
        if (alone && !rule.companions.some((companion) => conditions[companion])) {
            const needed = rule.companions.map((claim) => claimLabel(provider, claim)).join(' or ')
            return `${claimLabel(provider, alone)} needs ${needed} too. ${rule.reason}`
        }
    }
    return undefined
}

export function conditionsError(
    conditions: Record<string, string>,
    provider: WorkloadProviderApi | null
): string | undefined {
    const required = provider?.required_condition_claims ?? []
    const missing = required.filter((claim) => !conditions[claim]).map((claim) => claimLabel(provider, claim))
    // Required and account claims match every run of the account, so a policy needs another condition too.
    const accountClaims = new Set([...required, ...(provider?.account_condition_claims ?? [])])
    const runClaims = (provider?.condition_claims ?? []).filter((claim) => !accountClaims.has(claim.name))
    const noRuns = runClaims.length > 0 && !runClaims.some((claim) => conditions[claim.name])
    return (
        (missing.length ? `Set these conditions: ${missing.join(', ')}` : undefined) ??
        companionError(conditions, provider) ??
        (noRuns ? 'Choose which runs can get a token' : undefined)
    )
}

/** Why the subject lookup can't serve these conditions, or undefined when it can. */
export function subjectLookupBlocked(
    conditions: Record<string, string>,
    provider: WorkloadProviderApi | null
): string | undefined {
    const unmet = Object.entries(provider?.subject_lookup_conditions ?? {}).find(
        ([claim, value]) => conditions[claim] !== value
    )
    return unmet
        ? `PostHog can look up the ID only when ${claimLabel(provider, unmet[0])} is ${unmet[1]}. Enter it by hand.`
        : undefined
}
