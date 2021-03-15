import React from 'react'
import { kea, useActions, useValues } from 'kea'

import { PageHeader } from 'lib/components/PageHeader'
import { Alert, Tabs } from 'antd'
import { ActionsTable } from 'scenes/actions/ActionsTable'
import { EventsTable } from './EventsTable'
import { EventsVolumeTable } from './EventsVolumeTable'
import { PropertiesVolumeTable } from './PropertiesVolumeTable'
import { eventsLogicType } from './EventsType'
import { userLogic } from 'scenes/userLogic'

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

function UsageDisabledWarning(): JSX.Element {
    return (
        <Alert
            type="warning"
            message={
                <>
                    Event usage is not enabled on your instance. If you want to enable event usage please set the follow
                    environment variable: <pre style={{ display: 'inline' }}>ASYNC_EVENT_PROPERTY_USAGE=1</pre>
                    <br />
                    <br />
                    Please note, enabling this environment variable can increase load considerably if you have a large
                    volume of events.
                </>
            }
        />
    )
}

export function ManageEvents(): JSX.Element {
    const { tab } = useValues(eventsLogic)
    const { setTab } = useActions(eventsLogic)

    const { user } = useValues(userLogic)
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
                    {user?.is_event_property_usage_enabled ? <EventsVolumeTable /> : <UsageDisabledWarning />}
                </Tabs.TabPane>
                <Tabs.TabPane tab="Properties Stats" key="properties">
                    See all property keys that have ever been sent to this team, including the volume and how often
                    queries where made using this property key.
                    <br />
                    <br />
                    {user?.is_event_property_usage_enabled ? <PropertiesVolumeTable /> : <UsageDisabledWarning />}
                </Tabs.TabPane>
            </Tabs>
        </div>
    )
}
