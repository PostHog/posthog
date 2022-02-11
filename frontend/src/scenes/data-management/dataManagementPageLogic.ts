import { kea } from 'kea'
import { dataManagementPageLogicType } from './dataManagementPageLogicType'
import { DataManagementTab } from 'scenes/data-management/types'

export const dataManagementPageLogic = kea<dataManagementPageLogicType>({
    path: ['scenes', 'data-management', 'dataManagementPageLogic'],
    actions: {
        setTab: (tab: DataManagementTab) => ({ tab }),
    },
    reducers: {
        tab: [
            DataManagementTab.Events as DataManagementTab,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    },
})
