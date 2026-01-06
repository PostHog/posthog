import { actions, kea, key, listeners, path, props, reducers } from 'kea'

import type { featureFlagEvaluationTagsLogicType } from './featureFlagEvaluationTagsLogicType'
import { featureFlagLogic } from './featureFlagLogic'

export interface FeatureFlagEvaluationTagsLogicProps {
    flagId?: number | string | null
    instanceId: string
}

export const featureFlagEvaluationTagsLogic = kea<featureFlagEvaluationTagsLogicType>([
    path(['scenes', 'feature-flags', 'featureFlagEvaluationTagsLogic']),
    props({} as FeatureFlagEvaluationTagsLogicProps),
    key((props) => `${props.flagId || 'new'}-${props.instanceId}`),

    actions({
        setIsEditing: (isEditing) => ({ isEditing }),
        setLocalTags: (tags) => ({ tags }),
        setLocalEvaluationTags: (evaluationTags) => ({ evaluationTags }),
        saveTagsAndEvaluationTags: true,
        cancelEditing: true,
    }),

    reducers({
        isEditing: [
            false,
            {
                setIsEditing: (_, { isEditing }) => isEditing,
                saveTagsAndEvaluationTags: () => false,
                cancelEditing: () => false,
            },
        ],
        localTags: [
            [] as string[],
            {
                setLocalTags: (_, { tags }) => tags,
            },
        ],
        localEvaluationTags: [
            [] as string[],
            {
                setLocalEvaluationTags: (_, { evaluationTags }) => evaluationTags,
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        saveTagsAndEvaluationTags: () => {
            featureFlagLogic.actions.saveFeatureFlag({
                tags: values.localTags,
                evaluation_tags: values.localEvaluationTags,
            })
        },
        cancelEditing: () => {
            actions.setIsEditing(false)
        },
    })),
])
