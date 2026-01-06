import { actions, kea, key, listeners, path, props, propsChanged, reducers } from 'kea'

import type { featureFlagEvaluationTagsLogicType } from './featureFlagEvaluationTagsLogicType'
import { featureFlagLogic } from './featureFlagLogic'

export interface FeatureFlagEvaluationTagsLogicProps {
    flagId?: number | string | null
    /** Differentiates multiple instances for the same flag (e.g., 'sidebar' vs 'form') */
    context: 'sidebar' | 'form' | 'static'
    tags: string[]
    evaluationTags: string[]
}

export const featureFlagEvaluationTagsLogic = kea<featureFlagEvaluationTagsLogicType>([
    path(['scenes', 'feature-flags', 'featureFlagEvaluationTagsLogic']),
    props({} as FeatureFlagEvaluationTagsLogicProps),
    key((props) => `${props.flagId ?? 'new'}-${props.context}`),

    actions({
        setIsEditing: (isEditing: boolean) => ({ isEditing }),
        setLocalTags: (tags: string[]) => ({ tags }),
        setLocalEvaluationTags: (evaluationTags: string[]) => ({ evaluationTags }),
        saveTagsAndEvaluationTags: true,
        cancelEditing: true,
    }),

    reducers(({ props }) => ({
        isEditing: [
            false,
            {
                setIsEditing: (_, { isEditing }) => isEditing,
                saveTagsAndEvaluationTags: () => false,
                cancelEditing: () => false,
            },
        ],
        localTags: [
            props.tags ?? ([] as string[]),
            {
                setLocalTags: (_, { tags }) => tags,
            },
        ],
        localEvaluationTags: [
            props.evaluationTags ?? ([] as string[]),
            {
                setLocalEvaluationTags: (_, { evaluationTags }) => evaluationTags,
            },
        ],
    })),

    propsChanged(({ actions, props, values }, oldProps) => {
        // Only sync from props when not editing - if props change during editing
        // (e.g., websocket update), we preserve the user's local edits
        if (!values.isEditing) {
            if (props.tags !== oldProps.tags) {
                actions.setLocalTags(props.tags)
            }
            if (props.evaluationTags !== oldProps.evaluationTags) {
                actions.setLocalEvaluationTags(props.evaluationTags)
            }
        }
    }),

    listeners(({ values }) => ({
        saveTagsAndEvaluationTags: () => {
            featureFlagLogic.actions.saveFeatureFlag({
                tags: values.localTags,
                evaluation_tags: values.localEvaluationTags,
            })
        },
    })),
])
