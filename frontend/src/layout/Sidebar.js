import './Sidebar.scss'
import React, { useState } from 'react'
import { router } from 'kea-router'
import { TeamInvitationModal } from 'lib/components/TeamInvitation'
import { Menu, Layout, Modal } from 'antd'
import {
    UserOutlined,
    FunnelPlotOutlined,
    SettingOutlined,
    RiseOutlined,
    PlusOutlined,
    SyncOutlined,
    AimOutlined,
    UsergroupAddOutlined,
    ContainerOutlined,
    LineChartOutlined,
    FundOutlined,
    ExperimentOutlined,
    ClockCircleOutlined,
    MessageOutlined,
    TeamOutlined,
} from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { sceneLogic } from 'scenes/sceneLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import whiteLogo from './../../public/posthog-logo-white.svg'
import { triggerResizeAfterADelay } from 'lib/utils'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'
import { HogIcon } from 'lib/icons/HogIcon'
import { ToolbarModal } from '~/layout/ToolbarModal/ToolbarModal'

const itemStyle = { display: 'flex', alignItems: 'center' }

function Logo() {
    return (
        <div
            className="row logo-row d-flex align-items-center justify-content-center"
            style={{ margin: 16, height: 42, whiteSpace: 'nowrap', width: 168, overflow: 'hidden' }}
        >
            <img className="logo posthog-logo" src={whiteLogo} style={{ maxHeight: '100%' }} />
        </div>
    )
}

// to show the right page in the sidebar
const sceneOverride = {
    action: 'actions',
    funnel: 'funnels',
    editFunnel: 'funnels',
    person: 'people',
    dashboard: 'dashboards',
    featureFlags: 'experiments',
}

// to show the open submenu
const submenuOverride = {
    actions: 'events',
    liveActions: 'events',
    sessions: 'events',
    cohorts: 'people',
    setup: 'settings',
    annotations: 'settings',
}

export function Sidebar({ user, sidebarCollapsed, setSidebarCollapsed }) {
    const [inviteModalOpen, setInviteModalOpen] = useState(false)
    const [toolbarModalOpen, setToolbarModalOpen] = useState(false)
    const collapseSidebar = () => {
        if (!sidebarCollapsed && window.innerWidth <= 991) {
            setSidebarCollapsed(true)
        }
    }
    const { scene, loadingScene } = useValues(sceneLogic)
    const { location } = useValues(router)
    const { push } = useActions(router)
    const { dashboards, pinnedDashboards } = useValues(dashboardsModel)

    useEscapeKey(collapseSidebar, [sidebarCollapsed])

    let activeScene = sceneOverride[loadingScene || scene] || loadingScene || scene
    const openSubmenu = submenuOverride[activeScene] || activeScene

    if (activeScene === 'dashboards') {
        const dashboardId = parseInt(location.pathname.split('/dashboard/')[1])
        const dashboard = dashboardId && dashboards.find((d) => d.id === dashboardId)
        if (dashboard && dashboard.pinned) {
            activeScene = `dashboard-${dashboardId}`
        }
    }

    return (
        <>
            <div
                className={`sidebar-responsive-overlay${!sidebarCollapsed ? ' open' : ''}`}
                onClick={collapseSidebar}
            />
            <Layout.Sider
                breakpoint="lg"
                collapsedWidth="0"
                className="bg-dark"
                collapsed={sidebarCollapsed}
                onCollapse={(sidebarCollapsed) => {
                    setSidebarCollapsed(sidebarCollapsed)
                    triggerResizeAfterADelay()
                }}
            >
                <Menu
                    className="h-100 bg-dark"
                    theme="dark"
                    selectedKeys={[activeScene]}
                    openKeys={[openSubmenu]}
                    mode="inline"
                >
                    <Logo />

                    <Menu.Item
                        key="toolbar"
                        style={{ ...itemStyle, background: 'hsla(210, 10%, 12%, 1)' }}
                        onClick={() => setToolbarModalOpen(true)}
                        data-attr="menu-item-toolbar"
                    >
                        <HogIcon style={{ width: '1.4em', marginLeft: '-0.2em', marginRight: 'calc(10px - 0.2em)' }} />
                        <span className="sidebar-label">Launch Toolbar!</span>
                    </Menu.Item>

                    {pinnedDashboards.map((dashboard, index) => (
                        <Menu.Item
                            key={`dashboard-${dashboard.id}`}
                            style={itemStyle}
                            data-attr={'pinned-dashboard-' + index}
                            title=""
                        >
                            <LineChartOutlined />
                            <span className="sidebar-label">{dashboard.name}</span>
                            <Link to={`/dashboard/${dashboard.id}`} onClick={collapseSidebar} />
                        </Menu.Item>
                    ))}

                    <Menu.Item key="dashboards" style={itemStyle} data-attr="menu-item-dashboards" title="">
                        <FundOutlined />
                        <span className="sidebar-label">Dashboards</span>
                        <Link to="/dashboard" onClick={collapseSidebar} />
                    </Menu.Item>

                    {pinnedDashboards.length > 0 ? <Menu.Divider /> : null}

                    <Menu.Item key="insights" style={itemStyle} data-attr="menu-item-insights" title="">
                        <RiseOutlined />
                        <span className="sidebar-label">{'Insights'}</span>
                        <Link to={'/insights?insight=TRENDS'} onClick={collapseSidebar} />
                    </Menu.Item>

                    <Menu.SubMenu
                        key="events"
                        title={
                            <span style={itemStyle} data-attr="menu-item-events">
                                <ContainerOutlined />
                                <span className="sidebar-label">{'Events'}</span>
                            </span>
                        }
                        onTitleClick={() => {
                            collapseSidebar()
                            location.pathname !== '/events' && push('/events')
                        }}
                    >
                        <Menu.Item key="events" style={itemStyle} data-attr="menu-item-all-events">
                            <ContainerOutlined />
                            <span className="sidebar-label">{'All Events'}</span>
                            <Link to={'/events'} onClick={collapseSidebar} />
                        </Menu.Item>
                        <Menu.Item key="actions" style={itemStyle} data-attr="menu-item-actions">
                            <AimOutlined />
                            <span className="sidebar-label">{'Actions'}</span>
                            <Link to={'/actions'} onClick={collapseSidebar} />
                        </Menu.Item>
                        <Menu.Item key="liveActions" style={itemStyle} data-attr="menu-item-live-actions">
                            <SyncOutlined />
                            <span className="sidebar-label">{'Live Actions'}</span>
                            <Link to={'/actions/live'} onClick={collapseSidebar} />
                        </Menu.Item>
                        <Menu.Item key="sessions" style={itemStyle} data-attr="menu-item-sessions">
                            <ClockCircleOutlined />
                            <span className="sidebar-label">{'Sessions'}</span>
                            <Link to={'/sessions'} onClick={collapseSidebar} />
                        </Menu.Item>
                    </Menu.SubMenu>

                    <Menu.SubMenu
                        key="people"
                        title={
                            <span style={itemStyle} data-attr="menu-item-people">
                                <UserOutlined />
                                <span className="sidebar-label">{'People'}</span>
                            </span>
                        }
                        onTitleClick={() => {
                            collapseSidebar()
                            location.pathname !== '/people' && push('/people')
                        }}
                    >
                        <Menu.Item key="people" style={itemStyle} data-attr="menu-item-all-people">
                            <UserOutlined />
                            <span className="sidebar-label">{'All Users'}</span>
                            <Link to={'/people'} onClick={collapseSidebar} />
                        </Menu.Item>
                        <Menu.Item key="cohorts" style={itemStyle} data-attr="menu-item-cohorts">
                            <UsergroupAddOutlined />
                            <span className="sidebar-label">{'Cohorts'}</span>
                            <Link to={'/people/cohorts'} onClick={collapseSidebar} />
                        </Menu.Item>
                    </Menu.SubMenu>

                    <Menu.Item key="funnels" style={itemStyle} data-attr="menu-item-funnels">
                        <FunnelPlotOutlined />
                        <span className="sidebar-label">{'Funnels'}</span>
                        <Link to={'/funnel'} onClick={collapseSidebar} />
                    </Menu.Item>
                    <Menu.Item key="experiments" style={itemStyle} data-attr="menu-item-feature-f">
                        <ExperimentOutlined />
                        <span className="sidebar-label">{'Experiments'}</span>
                        <Link to={'/experiments/feature_flags'} onClick={collapseSidebar} />
                    </Menu.Item>

                    <Menu.SubMenu
                        key="settings"
                        title={
                            <span style={itemStyle} data-attr="menu-item-settings">
                                <SettingOutlined />
                                <span className="sidebar-label">{'Settings'}</span>
                            </span>
                        }
                        onTitleClick={() => {
                            collapseSidebar()
                            location.pathname !== '/setup' && push('/setup')
                        }}
                    >
                        <Menu.Item key="setup" style={itemStyle} data-attr="menu-item-setup">
                            <SettingOutlined />
                            <span className="sidebar-label">{'Setup'}</span>
                            <Link to={'/setup'} onClick={collapseSidebar} />
                        </Menu.Item>
                        <Menu.Item key="annotations" style={itemStyle} data-attr="menu-item-annotations">
                            <MessageOutlined />
                            <span className="sidebar-label">{'Annotations'}</span>
                            <Link to={'/annotations'} onClick={collapseSidebar} />
                        </Menu.Item>
                    </Menu.SubMenu>

                    <Menu.Item key="team" style={itemStyle} data-attr="menu-item-team">
                        <TeamOutlined />
                        <span className="sidebar-label">{'Team'}</span>
                        <Link to={'/team'} onClick={collapseSidebar} />
                    </Menu.Item>

                    <Menu.Item
                        key="invite"
                        style={itemStyle}
                        onClick={() => setInviteModalOpen(true)}
                        data-attr="menu-item-invite-team"
                    >
                        <PlusOutlined />
                        <span className="sidebar-label">Invite Teammate</span>
                    </Menu.Item>
                </Menu>

                <Modal
                    bodyStyle={{ padding: 0 }}
                    visible={toolbarModalOpen}
                    footer={null}
                    onCancel={() => setToolbarModalOpen(false)}
                >
                    <ToolbarModal />
                </Modal>

                <TeamInvitationModal user={user} visible={inviteModalOpen} onCancel={() => setInviteModalOpen(false)} />
            </Layout.Sider>
        </>
    )
}
