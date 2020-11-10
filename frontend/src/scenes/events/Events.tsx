import React from 'react'
import { kea, useActions, useValues } from 'kea'

import { hot } from 'react-hot-loader/root'
import { PageHeader } from 'lib/components/PageHeader'
import { Tabs } from 'antd'
import { ActionsTable } from 'scenes/actions/ActionsTable'
import { EventsTable } from './EventsTable'
import { EventsVolumeTable } from './EventsVolumeTable'
import { PropertiesVolumeTable } from './PropertiesVolumeTable'

const eventsLogic = kea({
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
            if (tab !== values.tab && tab) actions.setTab(tab)
        },
    }),
})

export const ManageEvents = hot(_ManageEvents)
function _ManageEvents({}): JSX.Element {
    const { tab } = useValues(eventsLogic)
    const { setTab } = useActions(eventsLogic)

    return (
        <div className="manage-events" data-attr="manage-events-table">
            <PageHeader title="Manage Events" />
            <Tabs tabPosition="top" animated={false} activeKey={tab} onTabClick={setTab}>
                <Tabs.TabPane tab="Live Events" key="live">
                    <i>See all events that are being sent to this team in real time.</i>
                    <EventsTable />
                </Tabs.TabPane>
                <Tabs.TabPane tab="Actions" key="actions">
                    <ActionsTable />
                </Tabs.TabPane>
                <Tabs.TabPane tab="Events" key="events">
                    <i>
                        See all event names that have every been sent to this team, including the volume and how often
                        queries where made using this event.
                    </i>
                    <br />
                    <br />
                    <EventsVolumeTable />
                </Tabs.TabPane>
                <Tabs.TabPane tab="Properties" key="properties">
                    <i>
                        See all property keys that have every been sent to this team, including the volume and how often
                        queries where made using this property key.
                    </i>
                    <br />
                    <br />
                    <PropertiesVolumeTable />
                </Tabs.TabPane>
            </Tabs>
        </div>
    )
}
