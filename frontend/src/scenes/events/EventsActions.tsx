// Combines EventsTable & ActionsTable in a single view
import { Tabs } from 'antd'
import React from 'react'
import { hot } from 'react-hot-loader/root'

export const EventsActions = hot(_EventsActions)

export function _EventsActions(): JSX.Element {
    const { TabPane } = Tabs

    return (
        <>
            <Tabs defaultActiveKey="events">
                <TabPane tab="Events" key="events">
                    Content of Tab Pane 1
                </TabPane>
                <TabPane tab="Actions" key="actions">
                    Content of Tab Pane 2
                </TabPane>
            </Tabs>
        </>
    )
}
