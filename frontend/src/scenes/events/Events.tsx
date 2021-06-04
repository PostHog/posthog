import React from 'react'
import { kea, useActions, useValues } from 'kea'

import { Tabs } from 'antd'
import { ActionsTable } from 'scenes/actions/ActionsTable'
import { EventsTable } from './EventsTable'
import { EventsVolumeTable } from './volume-definitions/EventsVolumeTable'
import { PropertiesVolumeTable } from './volume-definitions/PropertiesVolumeTable'
import { eventsLogicType } from './EventsType'
import { DefinitionDrawer } from './volume-definitions/DefinitionDrawer'

const eventsLogic = kea<eventsLogicType>({
    actions: {
        setTab: (tab: string) => ({ tab }),
    },
    reducers: {
        tab: [
            'live',
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    },
    actionToUrl: ({ values }) => ({
        setTab: () => '/events' + (values.tab === 'live' ? '' : '/' + values.tab),
    }),
    urlToAction: ({ actions, values }) => ({
        '/events(/:tab)': ({ tab }: Record<string, string>) => {
            const currentTab = tab || 'live'
            if (currentTab !== values.tab) {
                actions.setTab(currentTab)
            }
        },
    }),
})

export function ManageEvents(): JSX.Element {
    const { tab } = useValues(eventsLogic)
    const { setTab } = useActions(eventsLogic)
    return (
        <div data-attr="manage-events-table" style={{ paddingTop: 32 }}>
            <Tabs tabPosition="top" animated={false} activeKey={tab} onTabClick={setTab}>
                <Tabs.TabPane tab="Events" key="live">
                    <EventsTable />
                </Tabs.TabPane>
                <Tabs.TabPane tab={<span data-attr="events-actions-tab">Actions</span>} key="actions">
                    <ActionsTable />
                </Tabs.TabPane>
                <Tabs.TabPane tab="Events Stats" key="stats">
                    <EventsVolumeTable />
                </Tabs.TabPane>
                <Tabs.TabPane tab="Properties Stats" key="properties">
                    <PropertiesVolumeTable />
                </Tabs.TabPane>
            </Tabs>
            <DefinitionDrawer />
        </div>
    )
}
