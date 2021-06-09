import { kea } from 'kea'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { encodeParams } from 'kea-router'
import { FeatureFlagType } from '~/types'
import { featureFlagsLogicType } from './featureFlagsLogicType'

export const featureFlagsLogic = kea<featureFlagsLogicType<FeatureFlagType>>({
    actions: {
        setEnabledFeatureFlags: (featureFlags: string[]) => ({ featureFlags }),
    },

    reducers: {
        enabledFeatureFlags: [
            [] as string[],
            {
                setEnabledFeatureFlags: (_, { featureFlags }) => featureFlags,
            },
        ],
        receivedFeatureFlags: [
            false,
            {
                setEnabledFeatureFlags: () => true,
            },
        ],
    },

    loaders: {
        allFeatureFlags: [
            [] as FeatureFlagType[],
            {
                // eslint-disable-next-line
                getFlags: async (_ = null, breakpoint: () => void) => {
                    const params = {
                        temporary_token: toolbarLogic.values.temporaryToken,
                    }
                    const url = `${toolbarLogic.values.apiURL}api/feature_flag/${encodeParams(params, '?')}`
                    const response = await fetch(url)
                    const results = await response.json()

                    if (response.status === 403) {
                        toolbarLogic.actions.authenticate()
                        return []
                    }

                    breakpoint()

                    if (!Array.isArray(results?.results)) {
                        throw new Error('Error loading feature flags!')
                    }

                    return results.results
                },
            },
        ],
    },

    selectors: {
        sortedFeatureFlags: [
            (s) => [s.allFeatureFlags],
            (allFeatureFlags): FeatureFlagType[] =>
                [...allFeatureFlags].sort((a, b) => (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled')),
        ],
        featureFlagCount: [(s) => [s.sortedFeatureFlags], (sortedFeatureFlags) => sortedFeatureFlags.length],
    },

    events: ({ actions }) => ({
        afterMount: () => {
            actions.getFlags()
            ;(window['posthog'] as any).onFeatureFlags(actions.setEnabledFeatureFlags)
        },
    }),
})
