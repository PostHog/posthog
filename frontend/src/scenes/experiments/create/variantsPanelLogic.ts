import { kea } from 'kea'

import api from 'lib/api'
import { toParams } from 'lib/utils'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { validateFeatureFlagKey } from 'scenes/feature-flags/featureFlagLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'

import type { Experiment, FeatureFlagType } from '~/types'

import type { variantsPanelLogicType } from './variantsPanelLogicType'

export const variantsPanelLogic = kea<variantsPanelLogicType>({
    key: (props) => props.experiment?.id || 'new',
    path: (key) => ['scenes', 'experiments', 'create', 'panels', 'variantsPanelLogic', key],
    props: {
        experiment: {} as Experiment,
        disabled: false as boolean,
    } as {
        experiment: Experiment
        disabled: boolean
    },
    connect: {
        values: [featureFlagsLogic, ['featureFlags'], experimentsLogic, ['experiments']],
        actions: [],
    },
    actions: {
        setMode: (mode: 'create' | 'link') => ({ mode }),
        validateFeatureFlagKey: (key: string) => ({ key }),
        clearFeatureFlagKeyValidation: true,

        setFeatureFlagKeyDirty: true,
        setLinkedFeatureFlag: (flag: FeatureFlagType | null) => ({ flag }),
    },
    reducers: ({ props }) => ({
        featureFlagKeyError: [
            null as string | null,
            {
                setFeatureFlagKeyError: (_, { error }) => error,
            },
        ],
        mode: [
            // if disabled, we've default to 'link' mode
            (props.disabled ? 'link' : 'create') as 'create' | 'link',
            {
                setMode: (state: 'create' | 'link', { mode }: { mode: 'create' | 'link' }) => {
                    // Prevent mode changes when editing
                    if (props.disabled) {
                        return state
                    }
                    return mode
                },
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
            // Initialize from experiment.feature_flag when disabled
            (props.disabled && props.experiment.feature_flag
                ? props.experiment.feature_flag
                : null) as FeatureFlagType | null,
            {
                setLinkedFeatureFlag: (_, { flag }) => flag,
            },
        ],
    }),
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
                clearFeatureFlagKeyValidation: () => null,
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
            if (mode === 'link') {
                // When switching to link mode, clear validation
                // In link mode, we're using an existing flag, so the key validation doesn't apply
                actions.clearFeatureFlagKeyValidation()
            } else if (mode === 'create' && props.experiment.feature_flag_key) {
                // When switching from link to create, validate the current key to show it's taken
                // Note: We use values.experiment (from createExperimentLogic connection) instead of props.experiment
                // because props are captured at mount time and don't update when the parent logic changes state
                actions.validateFeatureFlagKey(props.experiment.feature_flag_key)
            }
        },
        setLinkedFeatureFlag: () => {
            // When selecting a linked flag, clear validation
            // The linked flag's key already exists (that's the point!), so validation doesn't apply
            actions.clearFeatureFlagKeyValidation()
        },
    }),
})
