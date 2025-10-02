import { kea } from 'kea'

import api from 'lib/api'
import { toParams } from 'lib/utils'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { validateFeatureFlagKey } from 'scenes/feature-flags/featureFlagLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'

import type { FeatureFlagType } from '~/types'

import { featureFlagEligibleForExperiment } from '../utils'
import type { variantsPanelLogicType } from './variantsPanelLogicType'

export const variantsPanelLogic = kea<variantsPanelLogicType>({
    path: ['scenes', 'experiments', 'create', 'panels', 'variantsPanelLogic'],
    connect: {
        values: [featureFlagsLogic, ['featureFlags as existingFeatureFlags'], experimentsLogic, ['experiments']],
    },
    actions: {
        validateFeatureFlagKey: (key: string) => ({ key }),
        setFeatureFlagKeyError: (error: string | null) => ({ error }),
        searchFeatureFlags: (search: string) => ({ search }),
        resetFeatureFlagsSearch: true,
        loadAllEligibleFeatureFlags: true,
        generateFeatureFlagKey: (name: string) => ({ name }),
    },
    reducers: {
        featureFlagKeyError: [
            null as string | null,
            {
                setFeatureFlagKeyError: (_, { error }) => error,
            },
        ],
        generatedFeatureFlagKey: [
            null as string | null,
            {
                generateFeatureFlagKey: (_, { name }) => name,
            },
        ],
    },
    loaders: ({ values }) => ({
        featureFlagKeyValidation: [
            null as { valid: boolean; error: string | null } | null,
            {
                validateFeatureFlagKey: async ({ key }, breakpoint) => {
                    // First do client-side validation
                    const clientError = validateFeatureFlagKey(key)
                    if (clientError) {
                        return { valid: false, error: clientError }
                    }

                    // Debounce API call
                    await breakpoint(300)

                    // Check if key already exists in our unavailable keys set
                    if (values.unavailableFeatureFlagKeys.has(key)) {
                        return { valid: false, error: 'A feature flag with this key already exists.' }
                    }

                    // Double-check with API for recently created flags
                    const response = await api.get(`api/projects/@current/feature_flags/?${toParams({ search: key })}`)

                    if (response.results.length > 0) {
                        const exactMatch = response.results.find((flag: FeatureFlagType) => flag.key === key)
                        if (exactMatch) {
                            return { valid: false, error: 'A feature flag with this key already exists.' }
                        }
                    }

                    return { valid: true, error: null }
                },
            },
        ],
        availableFeatureFlags: [
            [] as FeatureFlagType[],
            {
                loadAllEligibleFeatureFlags: async () => {
                    // Load all feature flags without search filter
                    const response = await api.get(
                        `api/projects/@current/feature_flags/?${toParams({
                            limit: 100,
                            deleted: false,
                        })}`
                    )

                    // Filter for eligible feature flags
                    const eligibleFlags = response.results.filter((flag: FeatureFlagType) => {
                        try {
                            return featureFlagEligibleForExperiment(flag)
                        } catch {
                            return false
                        }
                    })

                    return eligibleFlags
                },
                searchFeatureFlags: async ({ search }) => {
                    const response = await api.get(
                        `api/projects/@current/feature_flags/?${toParams({
                            search: search || undefined,
                            limit: 100,
                            deleted: false,
                        })}`
                    )

                    // Filter for eligible feature flags
                    const eligibleFlags = response.results.filter((flag: FeatureFlagType) => {
                        try {
                            return featureFlagEligibleForExperiment(flag)
                        } catch {
                            return false
                        }
                    })

                    return eligibleFlags
                },
                resetFeatureFlagsSearch: () => [],
            },
        ],
        generatedKey: [
            null as string | null,
            {
                generateFeatureFlagKey: async ({ name }) => {
                    if (!name) {
                        return null
                    }

                    const baseKey = name
                        .toLowerCase()
                        .replace(/[^a-z0-9-_]+/g, '-')
                        .replace(/-+$/, '')
                        .replace(/^-+/, '')

                    let key = baseKey
                    let counter = 1

                    // Check against unavailable keys
                    while (values.unavailableFeatureFlagKeys.has(key)) {
                        key = `${baseKey}-${counter}`
                        counter++
                    }

                    return key
                },
            },
        ],
    }),
    selectors: {
        unavailableFeatureFlagKeys: [
            (s) => [s.existingFeatureFlags, s.experiments],
            (featureFlags, experiments): Set<string> => {
                return new Set([
                    ...featureFlags.results.map((flag) => flag.key),
                    ...experiments.results.map((experiment) => experiment.feature_flag_key).filter(Boolean),
                ])
            },
        ],
    },
})
