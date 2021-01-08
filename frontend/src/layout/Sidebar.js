import './Sidebar.scss'
import React, { useState } from 'react'
import { router } from 'kea-router'
import { Menu, Layout, Modal } from 'antd'
import {
    SmileOutlined,
    TeamOutlined,
    UserOutlined,
    RiseOutlined,
    UsergroupAddOutlined,
    ContainerOutlined,
    LineChartOutlined,
    FundOutlined,
    FlagOutlined,
    ClockCircleOutlined,
    MessageOutlined,
    ProjectOutlined,
    SettingOutlined,
    LockOutlined,
    WalletOutlined,
    ApiOutlined,
    DatabaseOutlined,
    PlusOutlined,
} from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { sceneLogic } from 'scenes/sceneLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { triggerResizeAfterADelay } from 'lib/utils'
import { HogIcon } from 'lib/icons/HogIcon'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'
import { ToolbarModal } from '~/layout/ToolbarModal/ToolbarModal'
import whiteLogo from 'public/posthog-logo-white.svg'
import { hot } from 'react-hot-loader/root'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { CreateInviteModalWithButton } from 'scenes/organization/TeamMembers/CreateInviteModal'

const itemStyle = { display: 'flex', alignItems: 'center' }

function Logo() {
    return (
        <div className="sidebar-logo">
            <img src={whiteLogo} style={{ maxHeight: '100%' }} />
        </div>
    )
}

// to show the right page in the sidebar
const sceneOverride = {
    action: 'actions',
    person: 'persons',
    dashboard: 'dashboards',
    featureFlags: 'experiments',
}

// to show the open submenu
const submenuOverride = {
    actions: 'events',
    sessions: 'events',
    cohorts: 'persons',
    projectSettings: 'settings',
    plugins: 'settings',
    organizationSettings: 'settings',
    organizationMembers: 'settings',
    organizationInvites: 'settings',
    billing: 'settings',
    systemStatus: 'settings',
    instanceLicenses: 'settings',
    mySettings: 'settings',
}

export const Sidebar = hot(_Sidebar)
function _Sidebar({ user, sidebarCollapsed, setSidebarCollapsed }) {
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
                collapsed={sidebarCollapsed}
                onCollapse={(sidebarCollapsed) => {
                    setSidebarCollapsed(sidebarCollapsed)
                    triggerResizeAfterADelay()
                }}
                style={{ backgroundColor: 'var(--bg-menu)' }}
            >
                <Menu
                    className="h-100"
                    theme="dark"
                    style={{ backgroundColor: 'var(--bg-menu)' }}
                    selectedKeys={[activeScene]}
                    openKeys={[openSubmenu]}
                    mode="inline"
                >
                    <Logo />
                    {toolbarEnabled && (
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
                    )}
                    {pinnedDashboards.map((dashboard, index) => (
                        <Menu.Item
                            key={`dashboard-${dashboard.id}`}
                            style={itemStyle}
                            data-attr={'pinned-dashboard-' + index}
                            title=""
                        >
                            <LineChartOutlined />
                            <span className="sidebar-label">{dashboard.name || 'Untitled'}</span>
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

                    <Menu.Item key="events" style={itemStyle} data-attr="menu-item-events">
                        <ContainerOutlined />
                        Events & Actions
                        <Link to={'/events'} onClick={collapseSidebar} />
                    </Menu.Item>

                    <Menu.Item key="sessions" style={itemStyle} data-attr="menu-item-sessions">
                        <ClockCircleOutlined />
                        <span className="sidebar-label">{'Sessions'}</span>
                        <Link to={'/sessions'} onClick={collapseSidebar} />
                    </Menu.Item>

                    <Menu.SubMenu
                        key="persons"
                        title={
                            <span style={itemStyle} data-attr="menu-item-people">
                                <UserOutlined />
                                <span className="sidebar-label">{'People'}</span>
                            </span>
                        }
                        onTitleClick={() => {
                            collapseSidebar()
                            location.pathname !== '/persons' && push('/persons')
                        }}
                    >
                        <Menu.Item key="persons" style={itemStyle} data-attr="menu-item-persons">
                            <UserOutlined />
                            <span className="sidebar-label">Persons</span>
                            <Link to={'/persons'} onClick={collapseSidebar} />
                        </Menu.Item>
                        <Menu.Item key="cohorts" style={itemStyle} data-attr="menu-item-cohorts">
                            <UsergroupAddOutlined />
                            <span className="sidebar-label">Cohorts</span>
                            <Link to={'/cohorts'} onClick={collapseSidebar} />
                        </Menu.Item>
                    </Menu.SubMenu>

                    <Menu.Item key="experiments" style={itemStyle} data-attr="menu-item-feature-flags">
                        <FlagOutlined />
                        <span className="sidebar-label">Feature Flags</span>
                        <Link to={'/feature_flags'} onClick={collapseSidebar} />
                    </Menu.Item>

                    <Menu.Item key="annotations" style={itemStyle} data-attr="menu-item-annotations">
                        <MessageOutlined />
                        <span className="sidebar-label">Annotations</span>
                        <Link to={'/annotations'} onClick={collapseSidebar} />
                    </Menu.Item>

                    <Menu.SubMenu
                        key="settings"
                        title={
                            <span style={itemStyle} data-attr="menu-item-project">
                                <ProjectOutlined />
                                <span className="sidebar-label">Settings</span>
                            </span>
                        }
                        data-attr="menu-item-settings"
                        onTitleClick={() => {
                            collapseSidebar()
                            location.pathname !== '/project/settings' && push('/project/settings')
                        }}
                    >
                        <Menu.Item key="projectSettings" style={itemStyle} data-attr="menu-item-project-settings">
                            <SettingOutlined />
                            <span className="sidebar-label">Project Settings</span>
                            <Link to={'/project/settings'} onClick={collapseSidebar} />
                        </Menu.Item>
                        {user.plugin_access.configure && (
                            <Menu.Item key="plugins" style={itemStyle} data-attr="menu-item-plugins">
                                <ApiOutlined />
                                <span className="sidebar-label">Project Plugins</span>
                                <Link to="/project/plugins" onClick={collapseSidebar} />
                            </Menu.Item>
                        )}

                        <Menu.Item
                            key="organizationMembers"
                            style={itemStyle}
                            data-attr="menu-item-organization-members"
                        >
                            <TeamOutlined />
                            <span className="sidebar-label">Team Members</span>
                            <Link to={'/organization/members'} onClick={collapseSidebar} />
                        </Menu.Item>

                        {featureFlags['billing-management-page'] && (
                            <Menu.Item key="billing" style={itemStyle} data-attr="menu-item-organization-billing">
                                <WalletOutlined />
                                <span className="sidebar-label">Billing</span>
                                <Link to="/organization/billing" onClick={collapseSidebar} />
                            </Menu.Item>
                        )}

                        {(!user.is_multi_tenancy || (user.is_multi_tenancy && user.is_staff)) && (
                            <Menu.Item key="systemStatus" style={itemStyle} data-attr="menu-item-instance-status">
                                <DatabaseOutlined />
                                <span className="sidebar-label">System Status</span>
                                <Link to={'/instance/status'} onClick={collapseSidebar} />
                            </Menu.Item>
                        )}

                        {(!user.is_multi_tenancy || (user.is_multi_tenancy && user.is_staff)) && user.ee_available && (
                            <Menu.Item key="instanceLicenses" style={itemStyle} data-attr="menu-item-instance-licenses">
                                <LockOutlined />
                                <span className="sidebar-label">Licenses</span>
                                <Link to={'/instance/licenses'} onClick={collapseSidebar} />
                            </Menu.Item>
                        )}
                        <Menu.Item key="mySettings" style={itemStyle} data-attr="menu-item-my-settings">
                            <SmileOutlined />
                            <span className="sidebar-label">Me</span>
                            <Link to={'/me/settings'} onClick={collapseSidebar} />
                        </Menu.Item>
                    </Menu.SubMenu>
                    <Menu.Item key="inviteTeamMember" style={itemStyle} data-attr="menu-item-invite-teammate">
                        <PlusOutlined />
                        <CreateInviteModalWithButton type="sidebar" />
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
            </Layout.Sider>
        </>
    )
}
