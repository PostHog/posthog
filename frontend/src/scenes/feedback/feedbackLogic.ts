import { kea } from 'kea'

import type { feedbackLogicType } from './feedbackLogicType'

export const feedbackLogic = kea<feedbackLogicType>({
    path: ['scenes', 'feedback', 'feedbackLogic'],
    actions: {
        setTab: (activeTab: string) => ({ activeTab }),
    },
    reducers: {
        activeTab: [
            'in-app-feedback',
            {
                setTab: (_, { activeTab }) => activeTab,
            },
        ],
    },
})
