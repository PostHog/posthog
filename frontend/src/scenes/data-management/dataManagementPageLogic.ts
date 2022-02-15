import { kea } from 'kea'
import { dataManagementPageLogicType } from './dataManagementPageLogicType'
import { DataManagementTab } from 'scenes/data-management/types'
import { urls } from 'scenes/urls'
import { EventsTab } from 'scenes/events'

const tabUrls: Record<DataManagementTab, string> = {
    [DataManagementTab.Events]: urls.eventDefinitions(),
    [DataManagementTab.Actions]: urls.actionDefinitions(),
    [DataManagementTab.EventProperties]: urls.eventPropertyDefinitions(),
}

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
    actionToUrl: () => ({
        setTab: ({ tab }) => tabUrls[tab as EventsTab] || urls.events(),
    }),
    urlToAction: ({ actions, values }) => {
        return Object.fromEntries(
            Object.entries(tabUrls).map(([key, url]) => [
                url,
                () => {
                    if (values.tab !== key) {
                        actions.setTab(key as DataManagementTab)
                    }
                },
            ])
        )
    },
})
