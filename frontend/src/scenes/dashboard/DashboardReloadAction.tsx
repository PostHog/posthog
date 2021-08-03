import React, { useState } from 'react'
import { Checkbox, Dropdown, Menu, Radio, Space, Tooltip } from 'antd'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { LoadingOutlined, ReloadOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import dayjs from 'dayjs'
import { humanFriendlyDuration } from 'lib/utils'

export const LastRefreshText = (): JSX.Element => {
    const { lastRefreshed } = useValues(dashboardLogic)
    return (
        <>
            Last updated <b>{lastRefreshed ? dayjs(lastRefreshed).fromNow() : 'a while ago'}</b>
        </>
    )
}

// in seconds
const intervalOptions = [
    ...Array.from([10, 60, 120, 300, 900], (v) => ({
        label: humanFriendlyDuration(v),
        value: v,
    })),
]

export function DashboardReloadAction(): JSX.Element {
    const { itemsLoading, autoRefresh, refreshMetrics } = useValues(dashboardLogic)
    const { refreshAllDashboardItems, setAutoRefresh } = useActions(dashboardLogic)
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
                                    setAutoRefresh(true, e.target.value)
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
                onClick={() => refreshAllDashboardItems()}
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
                {itemsLoading ? (
                    <>
                        Refreshed {refreshMetrics.completed} out of {refreshMetrics.total}
                    </>
                ) : (
                    <LastRefreshText />
                )}
            </Dropdown.Button>
        </>
    )
}
