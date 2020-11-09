import React from 'react'
import { kea, useActions, useValues } from 'kea'

import { hot } from 'react-hot-loader/root'
import { PageHeader } from 'lib/components/PageHeader'
import { Table, Tabs } from 'antd'
import { userLogic } from 'scenes/userLogic'
import { actionsModel } from '~/models'
import { Link } from 'lib/components/Link'
import { ActionsTable } from 'scenes/actions/ActionsTable'

const manageEventsLogic = kea({
    connect: {
        values: [userLogic, ['eventNames'], actionsModel, ['actions']],
    },
})

function PropertiesVolumeTable(): JSX.Element {
    const columns = [
        {title: 'Property', dataIndex: 'property'}
    ]
    const { user } = useValues(userLogic)
    return <Table
        dataSource={user?.team.event_properties.map((name: string) => ({property: name}))}
        columns={columns}
        size="small"
        pagination={{ pageSize: 99999, hideOnSinglePage: true }}
    />
}

function EventsVolumeTable(): JSX.Element {
    const columns = [
        {title: 'Event', dataIndex: 'event'}
    ]
    const { user } = useValues(userLogic)
    return <Table
        dataSource={user?.team.event_names.map((name: string) => ({event: name}))}
        columns={columns}
        size="small"
        pagination={{ pageSize: 99999, hideOnSinglePage: true }}
    />
}

export const ManageEvents = hot(_ManageEvents)
function _ManageEvents({

}): JSX.Element {
    return (
        <div className="manage-events" data-attr="manage-events-table">
            <PageHeader title="Manage Events" />
            <Tabs
                tabPosition="top"
                animated={false}
            >
                <Tabs.TabPane
                    tab="Synthetic Events"
                    key="synthetic"
                >
                    <ActionsTable />
                </Tabs.TabPane>
                <Tabs.TabPane
                    tab="Events"
                    key="events"
                >
                    <EventsVolumeTable />
                </Tabs.TabPane>
                <Tabs.TabPane
                    tab="Properties"
                    key="properties"
                >
                    <PropertiesVolumeTable />
                </Tabs.TabPane>
            </Tabs>
        </div>
    )
}
