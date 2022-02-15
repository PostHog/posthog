import { PageHeader } from 'lib/components/PageHeader'
import { Tabs } from 'antd'
import { DataManagementTab } from 'scenes/data-management/types'
import { Tooltip } from 'lib/components/Tooltip'
import { InfoCircleOutlined } from '@ant-design/icons'
import React from 'react'
import { useActions, useValues } from 'kea'
import { dataManagementPageLogic } from 'scenes/data-management/dataManagementPageLogic'

export function DataManagementHeader(): JSX.Element {
    const { tab } = useValues(dataManagementPageLogic)
    const { setTab } = useActions(dataManagementPageLogic)

    return (
        <div className="data-management-header">
            <PageHeader
                title="Data Management"
                caption="Use data management to organize events that come into PostHog. Reduce noise, clarify usage, and help collaborators get the most value from your data."
                tabbedPage
            />
            <Tabs
                className="data-management-header-tabs"
                tabPosition="top"
                animated={false}
                activeKey={tab}
                onTabClick={(t) => setTab(t as DataManagementTab)}
            >
                <Tabs.TabPane tab="Events" key={DataManagementTab.Events} />
                <Tabs.TabPane
                    tab={
                        <>
                            Actions
                            <Tooltip title="Actions consist of one or more events that you have decided to put into a deliberately-labeled bucket. They're used in insights and dashboards.">
                                <InfoCircleOutlined className="info-icon ml-05" style={{ marginRight: 0 }} />
                            </Tooltip>
                        </>
                    }
                    key={DataManagementTab.Actions}
                />
                <Tabs.TabPane
                    tab={
                        <>
                            Properties
                            <Tooltip title="Properties are additional data sent along with an event capture. Use properties to understand additional information about events and the actors that generate them.">
                                <InfoCircleOutlined className="info-icon ml-05" style={{ marginRight: 0 }} />
                            </Tooltip>
                        </>
                    }
                    key={DataManagementTab.EventProperties}
                />
            </Tabs>
        </div>
    )
}
