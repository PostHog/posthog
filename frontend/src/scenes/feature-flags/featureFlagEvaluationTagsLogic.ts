import { actions, kea, listeners, path, props, reducers } from 'kea'

import type { featureFlagEvaluationTagsLogicType } from './featureFlagEvaluationTagsLogicType'

export interface FeatureFlagEvaluationTagsLogicProps {
    tags: string[]
    evaluationTags: string[]
}

export const featureFlagEvaluationTagsLogic = kea<featureFlagEvaluationTagsLogicType>([
    path(['scenes', 'feature-flags', 'featureFlagEvaluationTagsLogic']),
    props({} as FeatureFlagEvaluationTagsLogicProps),
    actions({
        setEditingTags: (editing: boolean) => ({ editing }),
        setShowEvaluationOptions: (show: boolean) => ({ show }),
        setSelectedTags: (tags: string[]) => ({ tags }),
        setSelectedEvaluationTags: (evaluationTags: string[]) => ({ evaluationTags }),
        resetSelectionsToProps: true,
    }),
    reducers(({ props }) => ({
        editingTags: [false as boolean, { setEditingTags: (_, { editing }) => editing }],
        showEvaluationOptions: [false as boolean, { setShowEvaluationOptions: (_, { show }) => show }],
        selectedTags: [
            props.tags as string[],
            {
                setSelectedTags: (_, { tags }) => tags,
                resetSelectionsToProps: () => props.tags as string[],
            },
        ],
        selectedEvaluationTags: [
            props.evaluationTags as string[],
            {
                setSelectedEvaluationTags: (_, { evaluationTags }) => evaluationTags,
                resetSelectionsToProps: () => props.evaluationTags as string[],
            },
        ],
    })),
    listeners(({ actions, values, props }) => ({
        setSelectedTags: () => {
            if (values.selectedTags.length === 0 && values.showEvaluationOptions) {
                actions.setShowEvaluationOptions(false)
            }
        },
        setEditingTags: ({ editing }) => {
            // When entering edit mode, seed selections from latest props
            if (editing) {
                actions.setSelectedTags([...(props.tags || [])])
                actions.setSelectedEvaluationTags([...(props.evaluationTags || [])])
            }
        },
    })),
])
