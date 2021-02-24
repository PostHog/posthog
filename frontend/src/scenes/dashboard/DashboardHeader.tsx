import './DashboardHeader.scss'

import { Loading, triggerResizeAfterADelay } from 'lib/utils'
import { Button, Dropdown, Menu, Select, Tooltip } from 'antd'
import { router } from 'kea-router'
import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { ShareModal } from './ShareModal'
import {
    PushpinFilled,
    PushpinOutlined,
    EllipsisOutlined,
    EditOutlined,
    DeleteOutlined,
    FullscreenOutlined,
    FullscreenExitOutlined,
    LockOutlined,
    UnlockOutlined,
    ShareAltOutlined,
    ReloadOutlined,
    CalendarOutlined,
} from '@ant-design/icons'
import { FullScreen } from 'lib/components/FullScreen'
import moment from 'moment'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardType } from '~/types'
import { DateFilter } from 'lib/components/DateFilter'

export function DashboardHeader(): JSX.Element {
    const { dashboard, draggingEnabled } = useValues(dashboardLogic)
    const {
        addNewDashboard,
        renameDashboard,
        enableDragging,
        disableDragging,
        updateAndRefreshDashboard,
        refreshAllDashboardItems,
    } = useActions(dashboardLogic)
    const { dashboards, dashboardsLoading } = useValues(dashboardsModel)
    const { pinDashboard, unpinDashboard, deleteDashboard } = useActions(dashboardsModel)
    const [fullScreen, setFullScreen] = useState(false)
    const [showShareModal, setShowShareModal] = useState(false)

    return (
        <div className={`dashboard-header${fullScreen ? ' full-screen' : ''}`}>
            {fullScreen ? <FullScreen onExit={() => setFullScreen(false)} /> : null}
            {showShareModal && <ShareModal onCancel={() => setShowShareModal(false)} />}
            {dashboardsLoading ? (
                <Loading />
            ) : (
                <>
                    <div className="dashboard-select">
                        <Select
                            value={dashboard?.id || null}
                            onChange={(id) =>
                                id === 'new' ? addNewDashboard() : router.actions.push(`/dashboard/${id}`)
                            }
                            bordered={false}
                            dropdownMatchSelectWidth={false}
                        >
                            {!dashboard ? <Select.Option value="">Not Found</Select.Option> : null}
                            {dashboards.map((dash: DashboardType) => (
                                <Select.Option key={dash.id} value={dash.id}>
                                    {dash.name || <span style={{ color: 'var(--gray)' }}>Untitled</span>}
                                </Select.Option>
                            ))}
                            <Select.Option value="new">+ New Dashboard</Select.Option>
                        </Select>
                        {dashboard.created_by ? (
                            <div className="dashboard-header-created-by">
                                Created by {dashboard.created_by.first_name || dashboard.created_by.email || '-'} on{' '}
                                {moment(dashboard.created_at).format(
                                    moment(dashboard.created_at).year() === moment().year() ? 'MMMM Do' : 'MMMM Do YYYY'
                                )}
                            </div>
                        ) : null}
                    </div>
                    {dashboard ? (
                        <div className="dashboard-meta">
                            <Tooltip title="Select time period">
                                <DateFilter
                                    defaultValue="Custom"
                                    showCustom
                                    onChange={updateAndRefreshDashboard}
                                    makeLabel={(key) => (
                                        <>
                                            <CalendarOutlined />
                                            <span className="hide-when-small"> {key}</span>
                                        </>
                                    )}
                                />
                            </Tooltip>

                            {!fullScreen ? (
                                <Tooltip title={dashboard.pinned ? 'Pinned into sidebar' : 'Pin into sidebar'}>
                                    <Button
                                        className="button-box-when-small"
                                        type={dashboard.pinned ? 'primary' : undefined}
                                        onClick={() =>
                                            dashboard.pinned ? unpinDashboard(dashboard.id) : pinDashboard(dashboard.id)
                                        }
                                    >
                                        {dashboard.pinned ? <PushpinFilled /> : <PushpinOutlined />}
                                        <span className="hide-when-small">{dashboard.pinned ? 'Pinned' : 'Pin'}</span>
                                    </Button>
                                </Tooltip>
                            ) : null}
                            <Tooltip title={'Share dashboard.'}>
                                <Button
                                    className="button-box-when-small enable-dragging-button"
                                    type={dashboard.is_shared ? 'primary' : undefined}
                                    onClick={() => setShowShareModal(true)}
                                    data-attr="dashboard-share-button"
                                >
                                    <ShareAltOutlined />
                                    <span className="hide-when-small">
                                        {dashboard.is_shared ? 'Shared' : 'Share dashboard'}
                                    </span>
                                </Button>
                            </Tooltip>

                            <Tooltip title="Click here to reload all dashboard items">
                                <Button className="button-box" onClick={refreshAllDashboardItems}>
                                    <ReloadOutlined />
                                </Button>
                            </Tooltip>

                            <Tooltip title="Click here or long press on a panel to rearrange the dashboard.">
                                <Button
                                    className="button-box enable-dragging-button"
                                    type={draggingEnabled === 'off' ? 'primary' : undefined}
                                    onClick={draggingEnabled === 'off' ? enableDragging : disableDragging}
                                >
                                    {draggingEnabled !== 'off' ? <UnlockOutlined /> : <LockOutlined />}
                                </Button>
                            </Tooltip>

                            <Tooltip title={fullScreen ? 'Presentation Mode Activated' : 'Activate Presentation Mode'}>
                                <Button
                                    className="button-box"
                                    onClick={() => {
                                        setFullScreen(!fullScreen)
                                        triggerResizeAfterADelay()
                                    }}
                                >
                                    {fullScreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
                                </Button>
                            </Tooltip>

                            {!fullScreen ? (
                                <Dropdown
                                    trigger={['click']}
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
