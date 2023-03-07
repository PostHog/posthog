import { kea } from 'kea'

import type { feedbackLogicType } from './feedbackLogicType'

export const feedbackLogic = kea<feedbackLogicType>({
    path: ['scenes', 'feedback', 'feedbackLogic'],
    actions: {
        setTab: (activeTab: string) => ({ activeTab }),
        toggleInAppFeedbackInstructions: true,
        setExpandedSection: (idx: number, expanded: boolean) => ({ idx, expanded }),
    },
    reducers: {
        activeTab: [
            'in-app-feedback',
            {
                setTab: (_, { activeTab }) => activeTab,
            },
        ],
        inAppFeedbackInstructions: [
            false,
            {
                toggleInAppFeedbackInstructions: (state) => !state,
            },
        ],
        expandedSections: [
            [false, false] as boolean[],
            {
                setExpandedSection: (state, { idx, expanded }) => {
                    const newState: boolean[] = [...state]
                    newState[idx] = expanded
                    return newState
                },
            },
        ],
    },
    selectors: {
        expandedSection: [
            (s) => [s.expandedSections],
            (expandedSections: boolean[]) => (idx: number) => expandedSections[idx],
        ],
    },
})
