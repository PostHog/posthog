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
import dayjs from 'dayjs'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardMode, DashboardType } from '~/types'
import { EventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
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
                                    {dayjs(dashboard.created_at).format(
                                        dayjs(dashboard.created_at).year() === dayjs().year()
                                            ? 'MMMM Do'
                                            : 'MMMM Do YYYY'
                                    )}
                                </Menu.Item>
                                <Menu.Divider />
                            </>
                        )}
                        <Menu.Item
                            icon={<EditOutlined />}
                            onClick={() => setDashboardMode(DashboardMode.Edit, EventSource.MoreDropdown)}
                        >
                            Edit mode (E)
                        </Menu.Item>
                        <Menu.Item
                            icon={<FullscreenOutlined />}
                            onClick={() => setDashboardMode(DashboardMode.Fullscreen, EventSource.MoreDropdown)}
                        >
                            Full screen mode (F)
                        </Menu.Item>
                        {dashboard.pinned ? (
                            <Menu.Item
                                icon={<PushpinFilled />}
                                onClick={() => unpinDashboard(dashboard.id, EventSource.MoreDropdown)}
                            >
                                Unpin dashboard
                            </Menu.Item>
                        ) : (
                            <Menu.Item
                                icon={<PushpinOutlined />}
                                onClick={() => pinDashboard(dashboard.id, EventSource.MoreDropdown)}
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
                onClick={() => setDashboardMode(DashboardMode.Edit, EventSource.DashboardHeader)}
            />
            <HotkeyButton
                onClick={() => addGraph()}
                data-attr="dashboard-add-graph-header"
                icon={<PlusOutlined />}
                hotkey="n"
                className="hide-lte-md"
            >
                Add graph
            </HotkeyButton>
            <HotkeyButton
                type="primary"
                onClick={() => setDashboardMode(DashboardMode.Sharing, EventSource.DashboardHeader)}
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
            onClick={() => setDashboardMode(null, EventSource.DashboardHeader)}
            data-attr="dashboard-exit-presentation-mode"
            icon={<FullscreenExitOutlined />}
        >
            Exit full screen mode
        </Button>
    )

    const actionsEditMode = (
        <Button
            data-attr="dashboard-edit-mode-save"
            type="primary"
            onClick={() => setDashboardMode(null, EventSource.DashboardHeader)}
        >
            Finish editing
        </Button>
    )

    return (
        <div className={`dashboard-header${dashboardMode === DashboardMode.Fullscreen ? ' full-screen' : ''}`}>
            {dashboardMode === DashboardMode.Fullscreen && (
                <FullScreen onExit={() => setDashboardMode(null, EventSource.Browser)} />
            )}
            <ShareModal
                onCancel={() => setDashboardMode(null, EventSource.Browser)}
                visible={dashboardMode === DashboardMode.Sharing}
            />
            {dashboardsLoading ? (
                <Loading />
            ) : (
                <>
                    {dashboardMode === DashboardMode.Edit ? (
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
                                    setDashboardMode(null, EventSource.InputEnter)
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
                        {dashboardMode === DashboardMode.Edit
                            ? actionsEditMode
                            : dashboardMode === DashboardMode.Fullscreen
                            ? actionsPresentationMode
                            : actionsDefault}
                    </div>
                </>
            )}
        </div>
    )
}
