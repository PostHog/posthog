import React from 'react'
import { kea, useActions } from 'kea'
import { Tabs } from 'antd'
import { urls } from 'scenes/urls'
import type { eventsTabsLogicType } from './DataManagementPageTabsType'
import { Tooltip } from 'lib/components/Tooltip'
import { IconInfo } from 'lib/components/icons'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'

export enum DataManagementTab {
    Actions = 'actions',
    EventDefinitions = 'events',
    EventPropertyDefinitions = 'properties',
}

const tabUrls: Record<DataManagementTab, string> = {
    [DataManagementTab.EventPropertyDefinitions]: urls.eventPropertyDefinitions(),
    [DataManagementTab.EventDefinitions]: urls.eventDefinitions(),
    [DataManagementTab.Actions]: urls.actions(),
}

const eventsTabsLogic = kea<eventsTabsLogicType>({
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
            <Tabs.TabPane
                tab={<span data-attr="data-management-events-tab">Events</span>}
                key={DataManagementTab.EventDefinitions}
            />
            <Tabs.TabPane
                tab={
                    <TitleWithIcon
                        icon={
                            <Tooltip title="Actions consist of one or more events that you have decided to put into a deliberately-labeled bucket. They're used in insights and dashboards.">
                                <IconInfo />
                            </Tooltip>
                        }
                        data-attr="data-management-actions-tab"
                    >
                        Actions
                    </TitleWithIcon>
                }
                key={DataManagementTab.Actions}
            />
            <Tabs.TabPane
                tab={
                    <TitleWithIcon
                        icon={
                            <Tooltip title="Properties are additional data sent along with an event capture. Use properties to understand additional information about events and the actors that generate them.">
                                <IconInfo />
                            </Tooltip>
                        }
                        data-attr="data-management-event-properties-tab"
                    >
                        Properties
                    </TitleWithIcon>
                }
                key={DataManagementTab.EventPropertyDefinitions}
            />
        </Tabs>
    )
}
