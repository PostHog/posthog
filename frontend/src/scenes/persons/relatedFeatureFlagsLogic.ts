import { actions, connect, events, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import type { relatedFeatureFlagsLogicType } from './relatedFeatureFlagsLogicType'

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

export const relatedFeatureFlagsLogic = kea<relatedFeatureFlagsLogicType>([
    path(['scenes', 'persons', 'relatedFeatureFlagsLogic']),
    connect({ values: [teamLogic, ['currentTeamId']] }),
    // actions({
    //     loadRelatedFeatureFlags: true,
    // }),
    props(
        {} as {
            distinctId: string
        }
    ),
    key((props) => `${props.distinctId}`),
    loaders(({ values }) => ({
        relatedFeatureFlags: [
            [] as RelatedFeatureFlagType[],
            {
                loadRelatedFeatureFlags: async () => {
                    // const response = await api.get(
                    //     `api/projects/${values.currentTeamId}/feature_flags/evaluation_reasons?${toParams({
                    //         distinct_id: props.distinctId,
                    //     })}`
                    // )
                    // return response || {}
                    const response = {
                        'alpha-feature': {
                            value: 'first-variant',
                            evaluation: {
                                reason: 'condition_match',
                                condition_index: 0,
                            },
                        },
                        'beta-feature': {
                            value: true,
                            evaluation: {
                                reason: 'condition_match',
                                condition_index: 0,
                            },
                        },
                        'group-feature': {
                            value: false,
                            evaluation: {
                                reason: 'no_group_type',
                                condition_index: null,
                            },
                        },
                        'inactive-flag': {
                            value: false,
                            evaluation: {
                                reason: 'disabled',
                                condition_index: null,
                            },
                        },
                    }
                    debugger
                    return Object.entries(response).map(([key, values]) => ({ [key]: values }))

                    // return
                },
            },
        ],
    })),
    // events(({ actions }) => ({
    //     afterMount: actions.loadRelatedFeatureFlags,
    // })),
])
