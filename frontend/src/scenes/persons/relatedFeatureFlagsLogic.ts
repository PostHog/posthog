import { actions, connect, events, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

export interface RelatedFeatureFlagType {
    [flag: string]: EvaluationReason
}

interface EvaluationReason {
    value: boolean
    evaluation: {
        reason: string
        condition_index: number
    }
}

export const relatedFeatureFlagsLogic = kea<relatedFeatureFlagsLogic>([
    path(['scenes', 'persons', 'relatedGroupsLogic']),
    connect({ values: [teamLogic, ['currentTeamId']] }),
    actions({
        loadRelatedFeatureFlags: true,
    }),
    props(
        {} as {
            distinctId: string
        }
    ),
    key((props) => `${props.distinctId}`),
    loaders(({ values }) => ({
        relatedFeatureFlags: [
            {} as RelatedFeatureFlagType,
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
    events(({ actions }) => ({
        afterMount: actions.loadRelatedFeatureFlags,
    })),
])
