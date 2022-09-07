import { actions, connect, events, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { FeatureFlagType } from '~/types'

import type { relatedFeatureFlagsLogicType } from './relatedFeatureFlagsLogicType'
export interface RelatedFeatureFlag extends FeatureFlagType {
    value: boolean
    evaluation: FeatureFlagEvaluationType
}

export interface FeatureFlagEvaluationType {
    reason: string
    condition_index?: number
}

interface RelatedFeatureFlagResponse {
    [key: string]: {
        value: boolean
        evaluation: FeatureFlagEvaluationType
    }
}

export const relatedFeatureFlagsLogic = kea<relatedFeatureFlagsLogicType>([
    path(['scenes', 'persons', 'relatedFeatureFlagsLogic']),
    connect({ values: [teamLogic, ['currentTeamId'], featureFlagsLogic, ['featureFlags']] }),
    props(
        {} as {
            distinctId: string
        }
    ),
    key((props) => `${props.distinctId}`),
    actions({
        loadRelatedFeatureFlags: true,
    }),
    loaders(({ values, props }) => ({
        relatedFeatureFlags: [
            null as RelatedFeatureFlagResponse | null,
            {
                loadRelatedFeatureFlags: async () => {
                    const response = await api.get(
                        `api/projects/${values.currentTeamId}/feature_flags/evaluation_reasons?${toParams({
                            distinct_id: props.distinctId,
                        })}`
                    )
                    return response
                },
            },
        ],
    })),
    selectors(() => ({
        mappedRelatedFeatureFlags: [
            (selectors) => [selectors.relatedFeatureFlags, selectors.featureFlags],
            (relatedFlags, featureFlags): RelatedFeatureFlag[] => {
                if (relatedFlags && featureFlags) {
                    const res = featureFlags.map((flag) => ({ ...relatedFlags[flag.key], ...flag }))
                    return res
                }
                return []
            },
        ],
    })),
    events(({ actions }) => ({
        afterMount: actions.loadRelatedFeatureFlags,
    })),
])
