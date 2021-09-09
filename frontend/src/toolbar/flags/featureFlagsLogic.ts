import { kea } from 'kea'
import { CombinedFeatureFlagAndOverride } from '~/types'
import { featureFlagsLogicType } from './featureFlagsLogicType'
import { PostHog } from 'posthog-js'
import { toolbarFetch } from '~/toolbar/utils'
import { toolbarLogic } from '~/toolbar/toolbarLogic'

export const featureFlagsLogic = kea<featureFlagsLogicType>({
    actions: {
        getUserFlags: true,
        setOverriddenUserFlag: (flagId: number, overrideValue: string | boolean) => ({ flagId, overrideValue }),
        deleteOverriddenUserFlag: (overrideId: number) => ({ overrideId }),
    },

    loaders: ({ values }) => ({
        userFlags: [
            [] as CombinedFeatureFlagAndOverride[],
            {
                getUserFlags: async (_, breakpoint) => {
                    const response = await toolbarFetch('api/feature_flag/my_flags')
                    breakpoint()
                    if (response.status === 403) {
                        return []
                    }
                    const results = await response.json()
                    return results.flags
                },
                setOverriddenUserFlag: async ({ flagId, overrideValue }, breakpoint) => {
                    const response = await toolbarFetch(
                        'api/projects/@current/feature_flag_overrides/my_overrides',
                        'POST',
                        {
                            feature_flag: flagId,
                            override_value: overrideValue,
                        }
                    )
                    breakpoint()
                    if (response.status === 403) {
                        return []
                    }
                    const results = await response.json()
                    return [...values.userFlags].map((userFlag) =>
                        userFlag.feature_flag.id === results.feature_flag
                            ? { ...userFlag, override: results }
                            : userFlag
                    )
                },
                deleteOverriddenUserFlag: async ({ overrideId }, breakpoint) => {
                    const response = await toolbarFetch(
                        `api/projects/@current/feature_flag_overrides/${overrideId}`,
                        'DELETE'
                    )
                    breakpoint()
                    if (response.status === 403) {
                        return []
                    }
                    return [...values.userFlags].map((userFlag) =>
                        userFlag?.override?.id === overrideId ? { ...userFlag, override: null } : userFlag
                    )
                },
            },
        ],
    }),

    events: ({ actions }) => ({
        afterMount: () => {
            actions.getUserFlags()
            ;(window['posthog'] as PostHog).onFeatureFlags((_, variants) => {
                toolbarLogic.actions.updateFeatureFlags(variants)
            })
        },
    }),
})
