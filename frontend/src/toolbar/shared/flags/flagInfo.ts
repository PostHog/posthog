import type { flagsToolbarLogicValues } from './flagsToolbarLogic'

type FilteredFlag = flagsToolbarLogicValues['filteredFlags'][number]

/** One feature flag as the toolbar shows it, in a shape both forms can render and the extension can post. */
export interface FlagInfo {
    key: string
    id: number | null
    /** The value PostHog evaluates for the signed-in user. Choosing it again removes the override. */
    value: string | boolean
    currentValue: string | boolean
    hasOverride: boolean
    variants: { key: string; name: string | null; rolloutPercentage: number | null }[]
    payloadOverride: unknown
}

export function toFlagInfo({
    feature_flag,
    value,
    currentValue,
    hasOverride,
    payloadOverride,
}: FilteredFlag): FlagInfo {
    return {
        key: feature_flag.key,
        id: feature_flag.id ?? null,
        value,
        currentValue,
        hasOverride,
        variants: (feature_flag.filters?.multivariate?.variants ?? []).map((variant) => ({
            key: variant.key,
            name: variant.name ?? null,
            rolloutPercentage: variant.rollout_percentage ?? null,
        })),
        payloadOverride: payloadOverride ?? null,
    }
}
