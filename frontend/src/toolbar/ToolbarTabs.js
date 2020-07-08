import React from 'react'
import { useActions, useValues } from 'kea'
import { Tabs } from 'antd'
import { toolbarTabLogic } from '~/toolbar/toolbarTabLogic'

export function ToolbarTabs() {
    const { tab } = useValues(toolbarTabLogic)
    const { setTab } = useActions(toolbarTabLogic)

    return (
        <div>
            <Tabs onChange={setTab} activeKey={tab}>
                <Tabs.TabPane tab="Stats" key="stats" />
                <Tabs.TabPane tab="Actions" key="actions" />
            </Tabs>
        </div>
    )
}
