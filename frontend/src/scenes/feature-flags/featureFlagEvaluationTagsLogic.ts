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
        setIsEditingTags: (isEditing: boolean) => ({ isEditing }),
        setIsEditingContexts: (isEditing: boolean) => ({ isEditing }),
        setLocalTags: (tags: string[]) => ({ tags }),
        setLocalEvaluationTags: (evaluationTags: string[]) => ({ evaluationTags }),
        saveTags: true,
        saveContexts: true,
        cancelEditingTags: true,
        cancelEditingContexts: true,
    }),

    reducers(({ props }) => ({
        isEditingTags: [
            false,
            {
                setIsEditingTags: (_, { isEditing }) => isEditing,
                saveTags: () => false,
                cancelEditingTags: () => false,
            },
        ],
        isEditingContexts: [
            false,
            {
                setIsEditingContexts: (_, { isEditing }) => isEditing,
                saveContexts: () => false,
                cancelEditingContexts: () => false,
            },
        ],
        localTags: [
            props.tags ?? ([] as string[]),
            {
                setLocalTags: (_, { tags }) => tags,
                cancelEditingTags: () => props.tags ?? [],
            },
        ],
        localEvaluationTags: [
            props.evaluationTags ?? ([] as string[]),
            {
                setLocalEvaluationTags: (_, { evaluationTags }) => evaluationTags,
                cancelEditingContexts: () => props.evaluationTags ?? [],
            },
        ],
    })),

    propsChanged(({ actions, props, values }, oldProps) => {
        if (!values.isEditingTags && props.tags !== oldProps.tags) {
            actions.setLocalTags(props.tags)
        }
        if (!values.isEditingContexts && props.evaluationTags !== oldProps.evaluationTags) {
            actions.setLocalEvaluationTags(props.evaluationTags)
        }
    }),

    listeners(({ props, values }) => ({
        saveTags: () => {
            const { flagId } = props
            if (typeof flagId === 'number') {
                featureFlagLogic({ id: flagId }).actions.saveFeatureFlag({
                    tags: values.localTags,
                })
            }
        },
        saveContexts: () => {
            const { flagId } = props
            if (typeof flagId === 'number') {
                featureFlagLogic({ id: flagId }).actions.saveFeatureFlag({
                    evaluation_contexts: values.localEvaluationTags,
                })
            }
        },
    })),
])
