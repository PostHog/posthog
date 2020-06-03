import React from 'react'
import { useActions, useValues } from 'kea'
import { Tabs } from 'antd'
import { toolbarLogic } from '~/editor/toolbarLogic'

export function ToolbarTabs({ type }) {
    const { tab, newTab } = useValues(toolbarLogic)
    const { setTab } = useActions(toolbarLogic)

    return (
        <div className={type === 'floating' ? 'toolbar-block no-padding' : ''}>
            <Tabs onChange={setTab} activeKey={newTab || tab}>
                <Tabs.TabPane tab="Stats" key="stats" />
                <Tabs.TabPane tab="Actions" key="actions" />
                <Tabs.TabPane tab="Dashboards" key="dashboards" />
            </Tabs>
        </div>
    )
}
