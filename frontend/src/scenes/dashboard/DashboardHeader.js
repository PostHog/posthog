import './DashboardHeader.scss'

import { Loading, triggerResizeAfterADelay } from 'lib/utils'
import { Button, Dropdown, Menu, Select, Tooltip } from 'antd'
import { router } from 'kea-router'
import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import {
    PushpinFilled,
    PushpinOutlined,
    EllipsisOutlined,
    EditOutlined,
    DeleteOutlined,
    FullscreenOutlined,
    FullscreenExitOutlined,
    DragOutlined,
} from '@ant-design/icons'
import { FullScreen } from 'lib/components/FullScreen'

export function DashboardHeader({ logic }) {
    const { dashboard, draggingEnabled } = useValues(logic)
    const { addNewDashboard, renameDashboard, setDraggingEnabled } = useActions(logic)
    const { dashboards, dashboardsLoading } = useValues(dashboardsModel)
    const { pinDashboard, unpinDashboard, deleteDashboard } = useActions(dashboardsModel)
    const [fullScreen, setFullScreen] = useState(false)

    return (
        <div className={`dashboard-header${fullScreen ? ' full-screen' : ''}`}>
            {fullScreen ? <FullScreen onExit={() => setFullScreen(false)} /> : null}
            {dashboardsLoading ? (
                <Loading />
            ) : (
                <>
                    <div>
                        <Select
                            value={dashboard?.id || null}
                            onChange={id =>
                                id === 'new' ? addNewDashboard() : router.actions.push(`/dashboard/${id}`)
                            }
                            bordered={false}
                            dropdownMatchSelectWidth={false}
                        >
                            {!dashboard ? <Select.Option value={null}>Not Found</Select.Option> : null}
                            {dashboards.map(dash => (
                                <Select.Option key={dash.id} value={parseInt(dash.id)}>
                                    {dash.name || <span style={{ color: 'var(--gray)' }}>Untitled</span>}
                                </Select.Option>
                            ))}

                            <Select.Option value="new">+ New Dashboard</Select.Option>
                        </Select>
                    </div>
                    {dashboard ? (
                        <div className="dashboard-meta">
                            <Tooltip
                                title={
                                    draggingEnabled
                                        ? 'Click here to disable dragging'
                                        : 'Click here or long press on a panel to enable dragging'
                                }
                            >
                                <Button
                                    type={draggingEnabled ? 'primary' : ''}
                                    onClick={() => setDraggingEnabled(!draggingEnabled)}
                                >
                                    <DragOutlined /> {draggingEnabled ? 'Drag ON' : 'Drag OFF'}
                                </Button>
                            </Tooltip>

                            {!fullScreen ? (
                                <Button
                                    type={dashboard.pinned ? 'primary' : ''}
                                    onClick={() =>
                                        dashboard.pinned ? unpinDashboard(dashboard.id) : pinDashboard(dashboard.id)
                                    }
                                >
                                    {dashboard.pinned ? <PushpinFilled /> : <PushpinOutlined />}{' '}
                                    {dashboard.pinned ? 'Pinned' : 'Pin'}
                                </Button>
                            ) : null}

                            <Button
                                className="button-box"
                                onClick={() => {
                                    setFullScreen(!fullScreen)
                                    triggerResizeAfterADelay()
                                }}
                            >
                                {fullScreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
                            </Button>

                            {!fullScreen ? (
                                <Dropdown
                                    trigger="click"
                                    overlay={
                                        <Menu>
                                            <Menu.Item icon={<EditOutlined />} onClick={renameDashboard}>
                                                Rename "{dashboard.name}"
                                            </Menu.Item>
                                            <Menu.Item
                                                icon={<DeleteOutlined />}
                                                onClick={() => deleteDashboard({ id: dashboard.id, redirect: true })}
                                                className="text-danger"
                                            >
                                                Delete
                                            </Menu.Item>
                                        </Menu>
                                    }
                                    placement="bottomRight"
                                >
                                    <Button className="button-box">
                                        <EllipsisOutlined />
                                    </Button>
                                </Dropdown>
                            ) : null}
                        </div>
                    ) : null}
                </>
            )}
        </div>
    )
}
