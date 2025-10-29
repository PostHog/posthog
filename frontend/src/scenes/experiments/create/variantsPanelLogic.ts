import { kea } from 'kea'

import api from 'lib/api'
import { toParams } from 'lib/utils'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { validateFeatureFlagKey } from 'scenes/feature-flags/featureFlagLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'

import type { Experiment, FeatureFlagType } from '~/types'

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
        actions: [],
    },
    actions: {
        setMode: (mode: 'create' | 'link') => ({ mode }),
        validateFeatureFlagKey: (key: string) => ({ key }),

        setFeatureFlagKeyDirty: true,
        setLinkedFeatureFlag: (flag: FeatureFlagType | null) => ({ flag }),
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
        linkedFeatureFlag: [
            null as FeatureFlagType | null,
            {
                setLinkedFeatureFlag: (_, { flag }) => flag,
            },
        ],
    },
    loaders: ({ values }) => ({
        featureFlagKeyValidation: [
            null as { valid: boolean; error: string | null } | null,
            {
                validateFeatureFlagKey: async ({ key }) => {
                    // First do client-side validation
                    const clientError = validateFeatureFlagKey(key)
                    if (clientError) {
                        return { valid: false, error: clientError }
                    }

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
    },
    listeners: ({ props, actions }) => ({
        setMode: ({ mode }) => {
            // When switching from link to create, validate the current key to show it's taken
            // Note: We use values.experiment (from createExperimentLogic connection) instead of props.experiment
            // because props are captured at mount time and don't update when the parent logic changes state
            if (mode === 'create' && props.experiment.feature_flag_key) {
                actions.validateFeatureFlagKey(props.experiment.feature_flag_key)
            }
        },
    }),
})
