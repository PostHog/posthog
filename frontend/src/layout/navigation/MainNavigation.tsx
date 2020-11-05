import React from 'react'
import { Menu, Layout } from 'antd'
import { RiseOutlined, FundOutlined } from '@ant-design/icons'
import { useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { sceneLogic } from 'scenes/sceneLogic'
import { triggerResizeAfterADelay } from 'lib/utils'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'
import whiteLogo from 'public/posthog-logo-white.svg'
import { hot } from 'react-hot-loader/root'
import './Navigation.scss'

function Logo(): JSX.Element {
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

export const MainNavigation = hot(_MainNavigation)
function _MainNavigation({ sidebarCollapsed, setSidebarCollapsed }): JSX.Element {
    const collapseSidebar = (): void => {
        if (!sidebarCollapsed && window.innerWidth <= 991) {
            setSidebarCollapsed(true)
        }
    }
    const { scene, loadingScene } = useValues(sceneLogic)

    useEscapeKey(collapseSidebar, [sidebarCollapsed])

    const activeScene = sceneOverride[loadingScene || scene] || loadingScene || scene

    return (
        <>
            <div
                className={`sidebar-responsive-overlay${!sidebarCollapsed ? ' open' : ''}`}
                onClick={collapseSidebar}
            />

            <Layout.Sider
                breakpoint="xxl"
                collapsedWidth={80}
                width={180}
                collapsed={sidebarCollapsed}
                onCollapse={(sidebarCollapsed) => {
                    setSidebarCollapsed(sidebarCollapsed)
                    triggerResizeAfterADelay()
                }}
                style={{ backgroundColor: 'var(--bg-menu)' }}
            >
                <Menu theme="dark" selectedKeys={[activeScene]} mode="vertical" className="navigation-main">
                    <Logo />

                    <Menu.Item key="dashboards" data-attr="menu-item-dashboards" title="" style={{}}>
                        <FundOutlined />
                        <p>Dashboards</p>
                        <Link to="/dashboard" onClick={collapseSidebar} />
                    </Menu.Item>
                    <Menu.Item key="funnels" data-attr="menu-item-funnels" title="">
                        <RiseOutlined />
                        <p>Funnels</p>
                        <Link to={'/insights?insight=FUNNELS'} onClick={collapseSidebar} />
                    </Menu.Item>
                    <Menu.Item key="insights" data-attr="menu-item-insights" title="">
                        <RiseOutlined />
                        <p>Insights</p>
                        <Link to={'/insights?insight=TRENDS'} onClick={collapseSidebar} />
                    </Menu.Item>
                    <Menu.Item key="retention" data-attr="menu-item-retention" title="">
                        <RiseOutlined />
                        <p>Retention</p>
                        <Link to={'/insights?insight=RETENTION'} onClick={collapseSidebar} />
                    </Menu.Item>
                    <Menu.Divider />
                    <Menu.Item key="feature-flags" data-attr="menu-item-feature-flags" title="">
                        <RiseOutlined />
                        <p>Feature Flags</p>
                        <Link to={'/feature_flags'} onClick={collapseSidebar} />
                    </Menu.Item>
                </Menu>
            </Layout.Sider>
        </>
    )
}
