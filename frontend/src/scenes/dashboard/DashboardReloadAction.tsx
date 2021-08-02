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
                    <Menu
                        data-attr="auto-refresh-picker"
                        id="auto-refresh-picker"
                        onSelect={({ key, domEvent }) => {
                            if (key === 'auto-refresh-check') {
                                domEvent.stopPropagation()
                                setOpen(true)
                                setAutoRefresh(!autoRefresh.enabled, autoRefresh.interval)
                            }
                        }}
                    >
                        <Menu.Item key="auto-refresh-check">
                            <Tooltip
                                title={`Refresh dashboard automatically every ${humanFriendlyDuration(
                                    autoRefresh.interval
                                )}`}
                                placement="bottomLeft"
                            >
                                <Checkbox
                                    id="auto-refresh"
                                    onChange={(e) => {
                                        e.stopPropagation()
                                        setAutoRefresh(e.target.checked, autoRefresh.interval)
                                    }}
                                    checked={autoRefresh.enabled}
                                />
                                <label
                                    style={{
                                        marginLeft: 10,
                                        cursor: 'pointer',
                                    }}
                                    htmlFor="auto-refresh"
                                >
                                    Auto refresh
                                </label>
                            </Tooltip>
                        </Menu.Item>
                        <Menu.Divider />
                        <Menu.ItemGroup title="Refresh interval">
                            <Radio.Group
                                onChange={(e) => {
                                    setAutoRefresh(true, e.target.value)
                                }}
                                value={autoRefresh.interval}
                            >
                                <Space direction="vertical">
                                    {intervalOptions.map(({ label, value }) => (
                                        <Radio key={value} value={value}>
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
