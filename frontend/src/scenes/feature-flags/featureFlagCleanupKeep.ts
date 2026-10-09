import { FeatureFlagType } from '~/types'

import type { FeatureFlagCleanupPrRequestApi } from 'products/feature_flags/frontend/generated/api.schemas'

const VARIANT_PREFIX = 'variant:'

export interface CleanupKeepOption {
    value: string
    label: string
}

export function getCleanupKeepOptions(featureFlag: Pick<FeatureFlagType, 'filters'>): CleanupKeepOption[] {
    const variants = featureFlag.filters?.multivariate?.variants ?? []
    if (variants.length === 0) {
        return [
            { value: 'enabled', label: 'The code that runs when the flag is on' },
            { value: 'disabled', label: 'The code that runs when the flag is off' },
        ]
    }
    return [
        ...variants.map((variant) => ({
            value: `${VARIANT_PREFIX}${variant.key}`,
            label: `The code for the ${variant.key} variant`,
        })),
        { value: 'disabled', label: 'The code that runs when the flag is off' },
    ]
}

export function cleanupKeepToRequest(
    keep: string,
    repository: string | null
): Pick<FeatureFlagCleanupPrRequestApi, 'keep' | 'variant_key' | 'repository'> {
    if (keep.startsWith(VARIANT_PREFIX)) {
        return { keep: 'variant', variant_key: keep.slice(VARIANT_PREFIX.length), repository }
    }
    return { keep: keep === 'enabled' ? 'enabled' : 'disabled', repository }
}
