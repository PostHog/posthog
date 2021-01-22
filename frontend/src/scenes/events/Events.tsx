import React from 'react'
import { kea, useActions, useValues } from 'kea'

import { hot } from 'react-hot-loader/root'
import { PageHeader } from 'lib/components/PageHeader'
import { Tabs } from 'antd'
import { ActionsTable } from 'scenes/actions/ActionsTable'
import { EventsTable } from './EventsTable'
import { EventsVolumeTable } from './EventsVolumeTable'
import { PropertiesVolumeTable } from './PropertiesVolumeTable'
import { eventsLogicType } from './EventsType'

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

export const ManageEvents = hot(_ManageEvents)
function _ManageEvents({}): JSX.Element {
    const { tab } = useValues(eventsLogic)
    const { setTab } = useActions(eventsLogic)

    return (
        <div className="manage-events" data-attr="manage-events-table">
            <PageHeader title="Events" />
            <Tabs tabPosition="top" animated={false} activeKey={tab} onTabClick={setTab}>
                <Tabs.TabPane tab="Events" key="live">
                    See all events that are being sent to this project in real time.
                    <EventsTable />
                </Tabs.TabPane>
                <Tabs.TabPane tab={<span data-attr="events-actions-tab">Actions</span>} key="actions">
                    <ActionsTable />
                </Tabs.TabPane>
                <Tabs.TabPane tab="Events Stats" key="stats">
                    See all event names that have ever been sent to this team, including the volume and how often
                    queries where made using this event.
                    <br />
                    <br />
                    <EventsVolumeTable />
                </Tabs.TabPane>
                <Tabs.TabPane tab="Properties Stats" key="properties">
                    See all property keys that have ever been sent to this team, including the volume and how often
                    queries where made using this property key.
                    <br />
                    <br />
                    <PropertiesVolumeTable />
                </Tabs.TabPane>
            </Tabs>
        </div>
    )
}
