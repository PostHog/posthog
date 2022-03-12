import React from 'react'
import { kea, useActions } from 'kea'
import { Tabs } from 'antd'
import { urls } from 'scenes/urls'
import { eventsTabsLogicType } from './DataManagementPageTabsType'

export enum DataManagementTab {
    Actions = 'actions',
    EventDefinitions = 'stats',
    EventPropertyDefinitions = 'properties',
}

const tabUrls: Record<DataManagementTab, string> = {
    [DataManagementTab.EventPropertyDefinitions]: urls.eventPropertyDefinitions(),
    [DataManagementTab.EventDefinitions]: urls.eventDefinitions(),
    [DataManagementTab.Actions]: urls.actions(),
}

const eventsTabsLogic = kea<eventsTabsLogicType<DataManagementTab>>({
    path: ['scenes', 'events', 'eventsTabsLogic'],
    actions: {
        setTab: (tab: DataManagementTab) => ({ tab }),
    },
    reducers: {
        tab: [
            DataManagementTab.EventDefinitions as DataManagementTab,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    },
    actionToUrl: () => ({
        setTab: ({ tab }) => tabUrls[tab as DataManagementTab] || urls.events(),
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

export function DataManagementPageTabs({ tab }: { tab: DataManagementTab }): JSX.Element {
    const { setTab } = useActions(eventsTabsLogic)
    return (
        <Tabs tabPosition="top" animated={false} activeKey={tab} onTabClick={(t) => setTab(t as DataManagementTab)}>
            <Tabs.TabPane tab={<span data-attr="events-actions-tab">Actions</span>} key="actions" />
            <Tabs.TabPane tab="Events" key="stats" />
            <Tabs.TabPane tab="Event Properties" key="properties" />
        </Tabs>
    )
}
