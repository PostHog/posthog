import React from 'react'
import { useActions, useValues } from 'kea'
import { Tabs } from 'antd'
import { toolbarTabLogic } from '~/toolbar/toolbarTabLogic'

export function ToolbarTabs({ type }) {
    const { tab, newTab } = useValues(toolbarTabLogic)
    const { setTab } = useActions(toolbarTabLogic)

    return (
        <div className={type === 'float' ? 'toolbar-block no-padding' : ''}>
            <Tabs onChange={setTab} activeKey={newTab || tab}>
                <Tabs.TabPane tab="Stats" key="stats" />
                <Tabs.TabPane tab="Actions" key="actions" />
                <Tabs.TabPane tab="Dashboards" key="dashboards" />
            </Tabs>
        </div>
    )
}
