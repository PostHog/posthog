import React from 'react'
import { kea, useActions } from 'kea'
import { Tabs } from 'antd'
import { urls } from 'scenes/urls'
import { eventsTabsLogicType } from './EventsTabsType'

export enum EventsTab {
    Events = 'events',
    Actions = 'actions',
    EventStats = 'stats',
    EventPropertyStats = 'properties',
}

const tabUrls: Record<EventsTab, string> = {
    [EventsTab.EventPropertyStats]: urls.eventPropertyStats(),
    [EventsTab.EventStats]: urls.eventStats(),
    [EventsTab.Actions]: urls.actions(),
    [EventsTab.Events]: urls.events(),
}

const eventsTabsLogic = kea<eventsTabsLogicType<EventsTab>>({
    actions: {
        setTab: (tab: EventsTab) => ({ tab }),
    },
    reducers: {
        tab: [
            EventsTab.Events as EventsTab,
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
                        actions.setTab(key as EventsTab)
                    }
                },
            ])
        )
    },
})

export function EventsTabs({ tab }: { tab: EventsTab }): JSX.Element {
    const { setTab } = useActions(eventsTabsLogic)
    return (
        <Tabs tabPosition="top" animated={false} activeKey={tab} onTabClick={(t) => setTab(t as EventsTab)}>
            <Tabs.TabPane tab="Events" key="events" />
            <Tabs.TabPane tab={<span data-attr="events-actions-tab">Actions</span>} key="actions" />
            <Tabs.TabPane tab="Events Stats" key="stats" />
            <Tabs.TabPane tab="Properties Stats" key="properties" />
        </Tabs>
    )
}
