import { kea } from 'kea'

import type { surveyAppearanceUtilsLogicType } from './surveyAppearanceUtilsLogicType'

export const surveyAppearanceUtilsLogic = kea<surveyAppearanceUtilsLogicType>({
    path: ['scenes', 'surveys', 'surveyAppearanceUtilsLogic'],

    actions: {
        setActiveTab: (activeTab: 'text' | 'html') => ({ activeTab }),
        initializeTab: (initialContentType: 'text' | 'html') => ({ initialContentType }),
    },
    reducers: {
        activeTab: [
            'text', // default value
            {
                setActiveTab: (_, { activeTab }) => activeTab,
                initializeTab: (_, { initialContentType }) => initialContentType,
            },
        ],
    },
    listeners: ({ actions }) => ({
        initializeTab: ({ initialContentType }) => {
            actions.setActiveTab(initialContentType)
        },
    }),
    defaults: {
        activeTab: (props) => props.initialContentType || 'text',
    },
    connect: {
        values: ['props'],
    },
})
