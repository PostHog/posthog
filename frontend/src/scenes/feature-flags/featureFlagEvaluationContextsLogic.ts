import { actions, kea, key, listeners, path, props, propsChanged, reducers } from 'kea'

import type { featureFlagEvaluationContextsLogicType } from './featureFlagEvaluationContextsLogicType'
import { featureFlagLogic } from './featureFlagLogic'

export interface FeatureFlagEvaluationContextsLogicProps {
    flagId?: number | string | null
    /** Differentiates multiple instances for the same flag (e.g., 'sidebar' vs 'form') */
    context: 'sidebar' | 'form' | 'static'
    tags: string[]
    evaluationContexts: string[]
}

export const featureFlagEvaluationContextsLogic = kea<featureFlagEvaluationContextsLogicType>([
    path(['scenes', 'feature-flags', 'featureFlagEvaluationContextsLogic']),
    props({} as FeatureFlagEvaluationContextsLogicProps),
    key((props) => `${props.flagId ?? 'new'}-${props.context}`),

    actions({
        setIsEditingTags: (isEditing: boolean) => ({ isEditing }),
        setIsEditingContexts: (isEditing: boolean) => ({ isEditing }),
        setLocalTags: (tags: string[]) => ({ tags }),
        setLocalEvaluationContexts: (evaluationContexts: string[]) => ({ evaluationContexts }),
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
        localEvaluationContexts: [
            props.evaluationContexts ?? ([] as string[]),
            {
                setLocalEvaluationContexts: (_, { evaluationContexts }) => evaluationContexts,
                cancelEditingContexts: () => props.evaluationContexts ?? [],
            },
        ],
    })),

    propsChanged(({ actions, props, values }, oldProps) => {
        if (!values.isEditingTags && props.tags !== oldProps.tags) {
            actions.setLocalTags(props.tags)
        }
        if (!values.isEditingContexts && props.evaluationContexts !== oldProps.evaluationContexts) {
            actions.setLocalEvaluationContexts(props.evaluationContexts)
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
                    evaluation_contexts: values.localEvaluationContexts,
                })
            }
        },
    })),
])
