import { actions, kea, path, reducers } from 'kea'

import type { feedbackLogicType } from './feedbackLogicType'

export const feedbackLogic = kea<feedbackLogicType>([
    path(['scenes', 'feedback', 'feedbackLogic']),
    actions({
        setActiveTab: (activeTab: string) => ({ activeTab }),
    }),
    reducers({
        activeTab: [
            'user-interview-scheduler' as string,
            {
                setActiveTab: (_, { activeTab }) => activeTab,
            },
        ],
    }),
])
