import React from 'react'
import { useActions, useValues } from 'kea'
import { Tabs } from 'antd'
import { toolbarTabLogic } from '~/toolbar/toolbarTabLogic'

export function ToolbarTabs(): JSX.Element {
    const { tab } = useValues(toolbarTabLogic)
    const { setTab } = useActions(toolbarTabLogic)

    return (
        <div>
            <Tabs onChange={(tab) => setTab(tab)} activeKey={tab}>
                <Tabs.TabPane tab="Stats" key="stats" />
                <Tabs.TabPane tab="Actions" key="actions" />
            </Tabs>
        </div>
    )
}
