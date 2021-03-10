import { Loading } from 'lib/utils'
import { Button, Dropdown, Input, Menu, Select, Tooltip } from 'antd'
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
    ShareAltOutlined,
} from '@ant-design/icons'
import { FullScreen } from 'lib/components/FullScreen'
import moment from 'moment'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardType } from '~/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export function DashboardHeader(): JSX.Element {
    const { dashboard, isOnEditMode, isOnFullScreenMode } = useValues(dashboardLogic)
    const { addNewDashboard, setIsOnEditMode, renameDashboard, setIsOnFullScreenMode } = useActions(dashboardLogic)
    const { dashboards, dashboardsLoading } = useValues(dashboardsModel)
    const { pinDashboard, unpinDashboard, deleteDashboard } = useActions(dashboardsModel)
    const [showShareModal, setShowShareModal] = useState(false)
    const [newDashboardName, setNewDashboardName] = useState(dashboard.name)

    const actionsDefault = (
        <>
            <Dropdown
                trigger={['click']}
                overlay={
                    <Menu>
                        {dashboard.created_by && (
                            <>
                                <Menu.Item disabled>
                                    Created by {dashboard.created_by.first_name || dashboard.created_by.email || '-'} on{' '}
                                    {moment(dashboard.created_at).format(
                                        moment(dashboard.created_at).year() === moment().year()
                                            ? 'MMMM Do'
                                            : 'MMMM Do YYYY'
                                    )}
                                </Menu.Item>
                                <Menu.Divider />
                            </>
                        )}
                        <Menu.Item icon={<EditOutlined />} onClick={() => setIsOnEditMode(true, 'more_dropdown')}>
                            Edit mode (E)
                        </Menu.Item>
                        <Menu.Item
                            icon={<FullscreenOutlined />}
                            onClick={() => setIsOnFullScreenMode(!isOnFullScreenMode, 'more_dropdown')}
                        >
                            Full screen mode (F)
                        </Menu.Item>
                        {dashboard.pinned ? (
                            <Menu.Item
                                icon={<PushpinFilled />}
                                onClick={() => unpinDashboard(dashboard.id, 'more_dropdown')}
                            >
                                Unpin dashboard
                            </Menu.Item>
                        ) : (
                            <Menu.Item
                                icon={<PushpinOutlined />}
                                onClick={() => pinDashboard(dashboard.id, 'more_dropdown')}
                            >
                                Pin dashboard
                            </Menu.Item>
                        )}

                        <Menu.Divider />
                        <Menu.Item
                            icon={<DeleteOutlined />}
                            onClick={() => deleteDashboard({ id: dashboard.id, redirect: true })}
                            danger
                        >
                            Delete dashboard
                        </Menu.Item>
                    </Menu>
                }
                placement="bottomRight"
            >
                <Button type="link" className="btn-lg-2x" data-attr="dashboard-more" icon={<EllipsisOutlined />} />
            </Dropdown>
            <Button
                type="link"
                data-attr="dashboard-edit-mode"
                icon={<EditOutlined />}
                onClick={() => setIsOnEditMode(true, 'dashboard_header')}
            />
            <Button
                type="primary"
                onClick={() => setShowShareModal(true)}
                data-attr="dashboard-share-button"
                icon={<ShareAltOutlined />}
            >
                Send or share
            </Button>
        </>
    )

    const actionsPresentationMode = (
        <Button
            onClick={() => setIsOnFullScreenMode(!isOnFullScreenMode, 'dashboard_header')}
            data-attr="dashboard-exit-presentation-mode"
            icon={<FullscreenExitOutlined />}
        >
            Exit presentation mode
        </Button>
    )

    const actionsEditMode = (
        <Button
            data-attr="dashboard-edit-mode-save"
            type="primary"
            onClick={() => setIsOnEditMode(false, 'dashboard_header')}
        >
            Finish editing
        </Button>
    )

    return (
        <div className={`dashboard-header${isOnFullScreenMode ? ' full-screen' : ''}`}>
            {isOnFullScreenMode && <FullScreen onExit={() => setIsOnFullScreenMode(false, 'browser')} />}
            {showShareModal && <ShareModal onCancel={() => setShowShareModal(false)} />}
            {dashboardsLoading ? (
                <Loading />
            ) : (
                <>
                    {isOnEditMode ? (
                        <Input
                            placeholder="Dashboard name (e.g. Weekly KPIs)"
                            value={newDashboardName}
                            autoFocus
                            size="large"
                            style={{ maxWidth: 400 }}
                            onChange={(e) => {
                                setNewDashboardName(e.target.value) // To update the input immediately
                                renameDashboard(e.target.value) // This is breakpointed (i.e. debounced) to avoid multiple API calls
                            }}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                    setIsOnEditMode(false, 'rename_input')
                                }
                            }}
                        />
                    ) : (
                        <div className="dashboard-select">
                            <Select
                                value={dashboard?.id || null}
                                onChange={(id) => {
                                    if (id === 'new') {
                                        addNewDashboard()
                                    } else {
                                        router.actions.push(`/dashboard/${id}`)
                                        eventUsageLogic.actions.reportDashboardDropdownNavigation()
                                    }
                                }}
                                bordered={false}
                                dropdownMatchSelectWidth={false}
                            >
                                {dashboards.map((dash: DashboardType) => (
                                    <Select.Option key={dash.id} value={dash.id}>
                                        {dash.name || <span style={{ color: 'var(--text-muted)' }}>Untitled</span>}
                                        {dash.is_shared && (
                                            <Tooltip title="This dashboard is publicly shared">
                                                <ShareAltOutlined style={{ marginLeft: 4, float: 'right' }} />
                                            </Tooltip>
                                        )}
                                    </Select.Option>
                                ))}
                                <Select.Option value="new">+ New Dashboard</Select.Option>
                            </Select>
                        </div>
                    )}

                    <div className="dashboard-meta">
                        {isOnEditMode ? (
                            <>{actionsEditMode}</>
                        ) : !isOnFullScreenMode ? (
                            <>{actionsDefault}</>
                        ) : (
                            <>{actionsPresentationMode}</>
                        )}
                    </div>
                </>
            )}
        </div>
    )
}
