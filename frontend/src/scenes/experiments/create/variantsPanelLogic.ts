import { kea } from 'kea'

import api from 'lib/api'
import { toParams } from 'lib/utils'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { validateFeatureFlagKey } from 'scenes/feature-flags/featureFlagLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'

import type { Experiment, FeatureFlagType } from '~/types'

import { featureFlagEligibleForExperiment } from '../utils'
import { createExperimentLogic } from './createExperimentLogic'
import type { variantsPanelLogicType } from './variantsPanelLogicType'

export const variantsPanelLogic = kea<variantsPanelLogicType>({
    path: ['scenes', 'experiments', 'create', 'panels', 'variantsPanelLogic'],
    props: {
        experiment: {} as Experiment,
    } as {
        experiment: Experiment
    },
    connect: {
        values: [featureFlagsLogic, ['featureFlags'], experimentsLogic, ['experiments']],
        actions: [createExperimentLogic, ['setExperimentValue']],
    },
    actions: {
        validateFeatureFlagKey: (key: string) => ({ key }),
        setFeatureFlagKeyError: (error: string | null) => ({ error }),
        searchFeatureFlags: (search: string) => ({ search }),
        resetFeatureFlagsSearch: true,
        loadAllEligibleFeatureFlags: true,
        generateFeatureFlagKey: (name: string) => ({ name }),
        setMode: (mode: 'create' | 'link') => ({ mode }),
        setFeatureFlagKeyDirty: true,
    },
    reducers: {
        featureFlagKeyError: [
            null as string | null,
            {
                setFeatureFlagKeyError: (_, { error }) => error,
            },
        ],
        mode: [
            'create' as 'create' | 'link',
            {
                setMode: (_: any, { mode }: { mode: 'create' | 'link' }) => mode,
            },
        ],
        featureFlagKeyDirty: [
            false,
            {
                setFeatureFlagKeyDirty: () => true,
                setMode: () => false, // Reset dirty flag when switching modes
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
        // TRICKY: we do not load all feature flags here, just the latest ones.
        unavailableFeatureFlagKeys: [
            (s) => [s.featureFlags, s.experiments],
            (featureFlags, experiments) => {
                return new Set([
                    ...featureFlags.results.map((flag) => flag.key),
                    ...experiments.results.map((experiment) => experiment.feature_flag_key),
                ])
            },
        ],
        featureFlagKey: [
            (_, props) => [props.experiment],
            (experiment: Experiment): string => experiment.feature_flag_key || '',
        ],
    },
    listeners: ({ values, actions }) => ({
        [createExperimentLogic.actionTypes.setExperimentValue]: ({ name, value }) => {
            if (name === 'name' && values.mode === 'create' && !values.featureFlagKeyDirty) {
                actions.generateFeatureFlagKey(value)
            }
        },
        generateFeatureFlagKeySuccess: ({ generatedKey }) => {
            if (generatedKey) {
                actions.setExperimentValue('feature_flag_key', generatedKey)
                actions.validateFeatureFlagKey(generatedKey)
            }
        },
    }),
})
