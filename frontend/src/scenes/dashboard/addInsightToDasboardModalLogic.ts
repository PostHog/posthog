import { actions, kea, path, reducers } from 'kea'

import type { addInsightToDashboardLogicType } from './addInsightToDasboardModalLogicType'

export const addInsightToDashboardLogic = kea<addInsightToDashboardLogicType>([
    path(['scenes', 'dashboard', 'addInsightToDashboardLogic']),
    actions({
        showAddInsightToDashboardModal: true,
        hideAddInsightToDashboardModal: true,
    }),
    reducers({
        addInsightToDashboardModalVisible: [
            false,
            {
                showAddInsightToDashboardModal: () => true,
                hideAddInsightToDashboardModal: () => false,
            },
        ],
    }),
])
