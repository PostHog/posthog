import { actions, events, kea, listeners, path, props, reducers } from 'kea'

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
    listeners(({ actions, values }) => ({
        setSelectedTags: () => {
            if (values.selectedTags.length === 0 && values.showEvaluationOptions) {
                actions.setShowEvaluationOptions(false)
            }
        },
    })),
    events(({ actions, values }) => ({
        propsChanged: (previousProps, nextProps) => {
            // When props change and we're not editing, sync the selections
            if (!values.editingTags) {
                const propsChanged =
                    previousProps.tags.join(',') !== nextProps.tags.join(',') ||
                    previousProps.evaluationTags.join(',') !== nextProps.evaluationTags.join(',')

                if (propsChanged) {
                    actions.setSelectedTags([...nextProps.tags])
                    actions.setSelectedEvaluationTags([...nextProps.evaluationTags])
                }
            }
        },
    })),
])
