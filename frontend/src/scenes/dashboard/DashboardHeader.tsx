import { Loading } from 'lib/utils'
import { Button, Dropdown, Input, Menu, Select, Tooltip } from 'antd'
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
    PlusOutlined,
} from '@ant-design/icons'
import { FullScreen } from 'lib/components/FullScreen'
import moment from 'moment'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardType } from '~/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { HotkeyButton } from 'lib/components/HotkeyButton'
import { router } from 'kea-router'

export function DashboardHeader(): JSX.Element {
    const { dashboard, dashboardMode } = useValues(dashboardLogic)
    const { addNewDashboard, renameDashboard, setDashboardMode, addGraph } = useActions(dashboardLogic)
    const { dashboards, dashboardsLoading } = useValues(dashboardsModel)
    const { pinDashboard, unpinDashboard, deleteDashboard } = useActions(dashboardsModel)
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
                        <Menu.Item icon={<EditOutlined />} onClick={() => setDashboardMode('edit', 'more_dropdown')}>
                            Edit mode (E)
                        </Menu.Item>
                        <Menu.Item
                            icon={<FullscreenOutlined />}
                            onClick={() => setDashboardMode('fullscreen', 'more_dropdown')}
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
                onClick={() => setDashboardMode('edit', 'dashboard_header')}
            />
            <HotkeyButton
                onClick={() => addGraph()}
                data-attr="dashboard-add-graph-header"
                icon={<PlusOutlined />}
                hotkey="n"
            >
                Add graph
            </HotkeyButton>
            <HotkeyButton
                type="primary"
                onClick={() => setDashboardMode('sharing', 'dashboard_header')}
                data-attr="dashboard-share-button"
                icon={<ShareAltOutlined />}
                hotkey="s"
            >
                Send or share
            </HotkeyButton>
        </>
    )

    const actionsPresentationMode = (
        <Button
            onClick={() => setDashboardMode(null, 'dashboard_header')}
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
            onClick={() => setDashboardMode(null, 'dashboard_header')}
        >
            Finish editing
        </Button>
    )

    return (
        <div className={`dashboard-header${dashboardMode === 'fullscreen' ? ' full-screen' : ''}`}>
            {dashboardMode === 'fullscreen' && <FullScreen onExit={() => setDashboardMode(null, 'browser')} />}
            <ShareModal onCancel={() => setDashboardMode(null, 'browser')} visible={dashboardMode === 'sharing'} />
            {dashboardsLoading ? (
                <Loading />
            ) : (
                <>
                    {dashboardMode === 'edit' ? (
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
                                    setDashboardMode(null, 'input_enter')
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
                        {dashboardMode === 'edit' ? (
                            <>{actionsEditMode}</>
                        ) : dashboardMode === 'fullscreen' ? (
                            <>{actionsPresentationMode}</>
                        ) : (
                            <>{actionsDefault}</>
                        )}
                    </div>
                </>
            )}
        </div>
    )
}
