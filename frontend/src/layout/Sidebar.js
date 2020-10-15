import './Sidebar.scss'
import React, { useState } from 'react'
import { router } from 'kea-router'
import { TeamInvitationModal } from 'lib/components/TeamInvitation'
import { Menu, Layout, Modal } from 'antd'
import {
    UserOutlined,
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
    LockOutlined,
    WalletOutlined,
    DatabaseOutlined,
} from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { sceneLogic } from 'scenes/sceneLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { triggerResizeAfterADelay } from 'lib/utils'
import { HogIcon } from 'lib/icons/HogIcon'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'
import { ToolbarModal } from '~/layout/ToolbarModal/ToolbarModal'
import whiteLogo from './../../public/posthog-logo-white.svg'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

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
    billing: 'settings',
    licenses: 'settings',
    systemStatus: 'settings',
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
    const { featureFlags } = useValues(featureFlagLogic)

    useEscapeKey(collapseSidebar, [sidebarCollapsed])

    const toolbarEnabled = user.toolbar_mode !== 'disabled'
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

                    {toolbarEnabled ? (
                        <Menu.Item
                            key="toolbar"
                            style={{ ...itemStyle, background: 'hsl(210, 10%, 11%)', fontWeight: 'bold' }}
                            onClick={() => setToolbarModalOpen(true)}
                            data-attr="menu-item-toolbar"
                        >
                            <div className="sidebar-toolbar-imitation">
                                <HogIcon />
                            </div>
                            <span className="sidebar-label">Launch Toolbar!</span>
                        </Menu.Item>
                    ) : null}

                    {pinnedDashboards.map((dashboard, index) => (
                        <Menu.Item
                            key={`dashboard-${dashboard.id}`}
                            style={itemStyle}
                            data-attr={'pinned-dashboard-' + index}
                            title=""
                        >
                            <LineChartOutlined />
                            <span className="sidebar-label">{dashboard.name ?? 'Untitled'}</span>
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
                                <span className="sidebar-label">
                                    {!featureFlags['actions-ux-201012'] ? 'Events' : 'Events & Actions'}
                                </span>
                            </span>
                        }
                        onTitleClick={() => {
                            collapseSidebar()
                            location.pathname !== '/events' && push('/actions')
                        }}
                    >
                        <Menu.Item key="events" style={itemStyle} data-attr="menu-item-all-events">
                            <ContainerOutlined />
                            <span className="sidebar-label">
                                {!featureFlags['actions-ux-201012'] ? 'All Events' : 'Raw Events'}
                            </span>
                            <Link to={'/events'} onClick={collapseSidebar} />
                        </Menu.Item>
                        <Menu.Item key="actions" style={itemStyle} data-attr="menu-item-actions">
                            <AimOutlined />
                            <span className="sidebar-label">{'Actions'}</span>
                            <Link to={'/actions'} onClick={collapseSidebar} />
                        </Menu.Item>
                        {!featureFlags['actions-ux-201012'] && (
                            <Menu.Item key="liveActions" style={itemStyle} data-attr="menu-item-live-actions">
                                <SyncOutlined />
                                <span className="sidebar-label">{'Live Actions'}</span>
                                <Link to={'/actions/live'} onClick={collapseSidebar} />
                            </Menu.Item>
                        )}
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

                        {featureFlags['billing-management-page'] && (
                            <Menu.Item key="billing" style={itemStyle} data-attr="menu-item-billing">
                                <WalletOutlined />
                                <span className="sidebar-label">Billing</span>
                                <Link to="/billing" onClick={collapseSidebar} />
                            </Menu.Item>
                        )}

                        {(!user.is_multi_tenancy || (user.is_multi_tenancy && user.is_staff)) && (
                            <Menu.Item key="systemStatus" style={itemStyle} data-attr="menu-item-system-status">
                                <DatabaseOutlined />
                                <span className="sidebar-label">System Status</span>
                                <Link to={'/system_status'} onClick={collapseSidebar} />
                            </Menu.Item>
                        )}

                        {!user.is_multi_tenancy && user.ee_available && (
                            <Menu.Item key="licenses" style={itemStyle} data-attr="menu-item-licenses">
                                <LockOutlined />
                                <span className="sidebar-label">Licenses</span>
                                <Link to={'/setup/licenses'} onClick={collapseSidebar} />
                            </Menu.Item>
                        )}
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
