import React, { useState } from 'react'
import { Checkbox, Dropdown, Menu, Radio, Space } from 'antd'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DownOutlined, LoadingOutlined, ReloadOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { humanFriendlyDuration } from 'lib/utils'
import clsx from 'clsx'
import { Tooltip } from 'lib/components/Tooltip'
import { dayjs } from 'lib/dayjs'

export const LastRefreshText = (): JSX.Element => {
    const { lastRefreshed } = useValues(dashboardLogic)
    return (
        <span>
            Last updated <b>{lastRefreshed ? dayjs(lastRefreshed).fromNow() : 'a while ago'}</b>
        </span>
    )
}

// in seconds
const intervalOptions = [
    ...Array.from([60, 120, 300, 900], (v) => ({
        label: humanFriendlyDuration(v),
        value: v,
    })),
]

export function DashboardReloadAction(): JSX.Element {
    const { itemsLoading, autoRefresh, refreshMetrics } = useValues(dashboardLogic)
    const { refreshAllDashboardItemsManual, setAutoRefresh } = useActions(dashboardLogic)
    const [open, setOpen] = useState(false)

    return (
        <>
            <Dropdown.Button
                overlay={
                    <Menu data-attr="auto-refresh-picker" id="auto-refresh-picker">
                        <div
                            id="auto-refresh-check"
                            key="auto-refresh-check"
                            onClick={(e) => {
                                e.stopPropagation()
                                setOpen(true)
                                setAutoRefresh(!autoRefresh.enabled, autoRefresh.interval)
                            }}
                        >
                            <Tooltip title={`Refresh dashboard automatically`} placement="bottomLeft">
                                <Checkbox
                                    onChange={(e) => {
                                        e.stopPropagation()
                                        e.preventDefault()
                                    }}
                                    checked={autoRefresh.enabled}
                                />
                                <label
                                    style={{
                                        marginLeft: 10,
                                        cursor: 'pointer',
                                    }}
                                >
                                    Auto refresh
                                </label>
                            </Tooltip>
                        </div>
                        <Menu.Divider />
                        <Menu.ItemGroup title="Refresh interval">
                            <Radio.Group
                                onChange={(e) => {
                                    setAutoRefresh(true, parseInt(e.target.value))
                                }}
                                value={autoRefresh.interval}
                                style={{ width: '100%' }}
                            >
                                <Space direction="vertical" style={{ width: '100%' }}>
                                    {intervalOptions.map(({ label, value }) => (
                                        <Radio key={value} value={value} style={{ width: '100%' }}>
                                            {label}
                                        </Radio>
                                    ))}
                                </Space>
                            </Radio.Group>
                        </Menu.ItemGroup>
                    </Menu>
                }
                trigger={['click']}
                onClick={() => refreshAllDashboardItemsManual()}
                icon={<DownOutlined />}
                disabled={itemsLoading}
                buttonsRender={([leftButton, rightButton]) => [
                    React.cloneElement(leftButton as React.ReactElement, { style: { paddingLeft: 10 } }),
                    rightButton,
                ]}
                visible={open}
                onVisibleChange={(toOpen) => setOpen(toOpen)}
            >
                <span className="dashboard-items-action-icon">
                    {itemsLoading ? <LoadingOutlined /> : <ReloadOutlined />}
                </span>
                <span className={clsx('dashboard-items-action-refresh-text', { hidden: itemsLoading })}>
                    <LastRefreshText />
                </span>
                <span className={clsx('dashboard-items-action-refresh-text', 'completed', { hidden: !itemsLoading })}>
                    Refreshed {refreshMetrics.completed} out of {refreshMetrics.total}
                </span>
            </Dropdown.Button>
        </>
    )
}
