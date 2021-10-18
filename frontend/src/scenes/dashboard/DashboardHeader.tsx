import { isMobile, Loading } from 'lib/utils'
import { Button, Dropdown, Input, Menu, Select } from 'antd'
import React, { useEffect, useRef, useState } from 'react'
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
import { AvailableFeature, DashboardMode, DashboardType } from '~/types'
import { DashboardEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { HotkeyButton } from 'lib/components/HotkeyButton'
import { router } from 'kea-router'
import { ObjectTags } from 'lib/components/ObjectTags'
import { dashboardsLogic } from './dashboardsLogic'
import { urls } from 'scenes/urls'
import { Description } from 'lib/components/Description/Description'
import { userLogic } from 'scenes/userLogic'
import { Tooltip } from 'lib/components/Tooltip'

export function DashboardHeader(): JSX.Element {
    const { dashboard, dashboardMode, lastDashboardModeSource } = useValues(dashboardLogic)
    const { addNewDashboard, triggerDashboardUpdate, setDashboardMode, addGraph, saveNewTag, deleteTag } =
        useActions(dashboardLogic)
    const { dashboardTags } = useValues(dashboardsLogic)
    const { nameSortedDashboards, dashboardsLoading, dashboardLoading } = useValues(dashboardsModel)
    const { pinDashboard, unpinDashboard, deleteDashboard } = useActions(dashboardsModel)
    const { user } = useValues(userLogic)
    const [newName, setNewName] = useState(dashboard?.name || null) // Used to update the input immediately, debouncing API calls

    const nameInputRef = useRef<Input | null>(null)
    const descriptionInputRef = useRef<HTMLInputElement | null>(null)

    if (!dashboard) {
        return <div />
    }

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
                            onClick={() => setDashboardMode(DashboardMode.Edit, DashboardEventSource.MoreDropdown)}
                        >
                            Edit mode (E)
                        </Menu.Item>
                        <Menu.Item
                            icon={<FullscreenOutlined />}
                            onClick={() =>
                                setDashboardMode(DashboardMode.Fullscreen, DashboardEventSource.MoreDropdown)
                            }
                        >
                            Full screen mode (F)
                        </Menu.Item>
                        {dashboard.pinned ? (
                            <Menu.Item
                                icon={<PushpinFilled />}
                                onClick={() => unpinDashboard(dashboard.id, DashboardEventSource.MoreDropdown)}
                            >
                                Unpin dashboard
                            </Menu.Item>
                        ) : (
                            <Menu.Item
                                icon={<PushpinOutlined />}
                                onClick={() => pinDashboard(dashboard.id, DashboardEventSource.MoreDropdown)}
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
                onClick={() => setDashboardMode(DashboardMode.Edit, DashboardEventSource.DashboardHeader)}
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
                onClick={() => setDashboardMode(DashboardMode.Sharing, DashboardEventSource.DashboardHeader)}
                data-attr="dashboard-share-button"
                icon={<ShareAltOutlined />}
                hotkey="k"
            >
                Send or share
            </HotkeyButton>
        </>
    )

    const actionsPresentationMode = (
        <Button
            onClick={() => setDashboardMode(null, DashboardEventSource.DashboardHeader)}
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
            onClick={() => setDashboardMode(null, DashboardEventSource.DashboardHeader)}
            tabIndex={10}
        >
            Finish editing
        </Button>
    )

    useEffect(() => {
        if (dashboardMode === DashboardMode.Edit) {
            if (lastDashboardModeSource === DashboardEventSource.AddDescription) {
                setTimeout(() => descriptionInputRef.current?.focus(), 10)
            } else if (!isMobile()) {
                setTimeout(() => nameInputRef.current?.focus(), 10)
            }
        }
    }, [dashboardMode])

    return (
        <>
            <div className={`dashboard-header${dashboardMode === DashboardMode.Fullscreen ? ' full-screen' : ''}`}>
                {dashboardMode === DashboardMode.Fullscreen && (
                    <FullScreen onExit={() => setDashboardMode(null, DashboardEventSource.Browser)} />
                )}
                <ShareModal
                    onCancel={() => setDashboardMode(null, DashboardEventSource.Browser)}
                    visible={dashboardMode === DashboardMode.Sharing}
                />
                {dashboardsLoading ? (
                    <Loading />
                ) : (
                    <>
                        {dashboardMode === DashboardMode.Edit ? (
                            <Input
                                placeholder="Dashboard name (e.g. Weekly KPIs)"
                                value={newName || ''}
                                size="large"
                                style={{ maxWidth: 400 }}
                                onChange={(e) => {
                                    setNewName(e.target.value) // To update the input immediately
                                    triggerDashboardUpdate({ name: e.target.value }) // This is breakpointed (i.e. debounced) to avoid multiple API calls
                                }}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') {
                                        setDashboardMode(null, DashboardEventSource.InputEnter)
                                    }
                                }}
                                ref={nameInputRef}
                                tabIndex={0}
                            />
                        ) : (
                            <div className="dashboard-select">
                                <Select
                                    value={(dashboard?.id || undefined) as number | 'new' | undefined}
                                    onChange={(id) => {
                                        if (id === 'new') {
                                            addNewDashboard()
                                        } else {
                                            router.actions.push(urls.dashboard(id))
                                            eventUsageLogic.actions.reportDashboardDropdownNavigation()
                                        }
                                    }}
                                    bordered={false}
                                    dropdownMatchSelectWidth={false}
                                >
                                    {nameSortedDashboards.map((dash: DashboardType) => (
                                        <Select.Option key={dash.id} value={dash.id}>
                                            {dash.name || <span style={{ color: 'var(--muted)' }}>Untitled</span>}
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
            {user?.organization?.available_features?.includes(AvailableFeature.DASHBOARD_COLLABORATION) && (
                <>
                    <div className="mb" data-attr="dashboard-tags">
                        <ObjectTags
                            tags={dashboard.tags}
                            onTagSave={saveNewTag}
                            onTagDelete={deleteTag}
                            saving={dashboardLoading}
                            tagsAvailable={dashboardTags.filter((tag) => !dashboard.tags.includes(tag))}
                        />
                    </div>
                    <Description
                        item={dashboard}
                        setItemMode={setDashboardMode}
                        itemMode={dashboardMode}
                        triggerItemUpdate={triggerDashboardUpdate}
                        descriptionInputRef={descriptionInputRef}
                    />
                </>
            )}
        </>
    )
}
