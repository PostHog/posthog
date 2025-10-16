import { actions, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import type { featureFlagEvaluationTagsLogicType } from './featureFlagEvaluationTagsLogicType'

export interface FeatureFlagEvaluationTagsLogicProps {
    tags: string[]
    evaluationTags: string[]
    flagId?: number | string | null
}

export const featureFlagEvaluationTagsLogic = kea<featureFlagEvaluationTagsLogicType>([
    path((key) => ['scenes', 'feature-flags', 'featureFlagEvaluationTagsLogic', key]),
    props({} as FeatureFlagEvaluationTagsLogicProps),
    key((props) => props.flagId || 'new'),
    actions({
        setEditingTags: (editing: boolean) => ({ editing }),
        setShowEvaluationOptions: (show: boolean) => ({ show }),
        setDraftTags: (tags: string[]) => ({ tags }),
        setDraftEvaluationTags: (evaluationTags: string[]) => ({ evaluationTags }),
    }),
    reducers(() => ({
        editingTags: [false as boolean, { setEditingTags: (_, { editing }) => editing }],
        showEvaluationOptions: [false as boolean, { setShowEvaluationOptions: (_, { show }) => show }],
        draftTags: [
            null as string[] | null,
            {
                setDraftTags: (_, { tags }) => tags,
                setEditingTags: (state, { editing }) => (editing ? state : null),
            },
        ],
        draftEvaluationTags: [
            null as string[] | null,
            {
                setDraftEvaluationTags: (_, { evaluationTags }) => evaluationTags,
                setEditingTags: (state, { editing }) => (editing ? state : null),
            },
        ],
    })),
    selectors({
        selectedTags: [
            (s) => [s.editingTags, s.draftTags, (_, props) => props.tags],
            (editingTags, draftTags, propsTags): string[] =>
                editingTags && draftTags !== null ? draftTags : propsTags || [],
        ],
        selectedEvaluationTags: [
            (s) => [s.editingTags, s.draftEvaluationTags, (_, props) => props.evaluationTags],
            (editingTags, draftEvaluationTags, propsEvaluationTags): string[] =>
                editingTags && draftEvaluationTags !== null ? draftEvaluationTags : propsEvaluationTags || [],
        ],
    }),
    listeners(({ actions, values, props }) => ({
        setDraftTags: () => {
            if (values.draftTags && values.draftTags.length === 0 && values.showEvaluationOptions) {
                actions.setShowEvaluationOptions(false)
            }
        },
        setEditingTags: ({ editing }) => {
            if (editing) {
                // When entering edit mode, initialize drafts from current props
                actions.setDraftTags(props.tags || [])
                actions.setDraftEvaluationTags(props.evaluationTags || [])
            } else {
                // Clear drafts when exiting edit mode
                actions.setDraftTags(null as any)
                actions.setDraftEvaluationTags(null as any)
            }
        },
    })),
    events(({ actions }) => ({
        beforeUnmount: () => {
            // Reset state when component unmounts to ensure fresh state for next mount
            actions.setEditingTags(false)
            actions.setShowEvaluationOptions(false)
        },
    })),
])
