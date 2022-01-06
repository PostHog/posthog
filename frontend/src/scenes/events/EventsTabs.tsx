import React from 'react'
import { kea, useActions } from 'kea'
import { Tabs } from 'antd'
import { urls } from 'scenes/urls'
import { eventsTabsLogicType } from './EventsTabsType'

export enum EventsTab {
    LiveEvents = 'live',
    Actions = 'actions',
    EventsStats = 'events_stats',
    EventPropertiesStats = 'properties_stats',
}

const tabUrls: Record<EventsTab, string> = {
    [EventsTab.EventPropertiesStats]: urls.eventPropertyStats(),
    [EventsTab.EventsStats]: urls.eventStats(),
    [EventsTab.Actions]: urls.actions(),
    [EventsTab.LiveEvents]: urls.events(),
}

const eventsTabsLogic = kea<eventsTabsLogicType<EventsTab>>({
    path: ['scenes', 'events', 'eventsTabsLogic'],
    actions: {
        setTab: (tab: EventsTab) => ({ tab }),
    },
    reducers: {
        tab: [
            EventsTab.LiveEvents as EventsTab,
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
            <Tabs.TabPane tab="Live" key={EventsTab.LiveEvents} />
            <Tabs.TabPane tab={<span data-attr="events-actions-tab">Actions</span>} key={EventsTab.Actions} />
            <Tabs.TabPane tab="Events" key={EventsTab.EventsStats} />
            <Tabs.TabPane tab="Properties" key={EventsTab.EventPropertiesStats} />
        </Tabs>
    )
}
