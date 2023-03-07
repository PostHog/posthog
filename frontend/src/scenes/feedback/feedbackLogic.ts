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
                    // set all to false apart from the one we're changing
                    return state.map((_, i) => (i === idx ? expanded : false))
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
