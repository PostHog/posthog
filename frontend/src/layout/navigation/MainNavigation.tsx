import React from 'react'
import { Layout } from 'antd'
import { FundOutlined } from '@ant-design/icons'
import { useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { sceneLogic } from 'scenes/sceneLogic'
import { triggerResizeAfterADelay } from 'lib/utils'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'
import lgLogo from 'public/posthog-logo-white.svg'
import smLogo from 'public/icon-white.svg'
import { hot } from 'react-hot-loader/root'
import './Navigation.scss'
import { IconDashboard, IconPerson } from './icons'

// to show the right page in the sidebar
const sceneOverride = {
    action: 'actions',
    person: 'persons',
    dashboard: 'dashboards',
    featureFlags: 'experiments',
}

const MenuItem = ({ title, icon, identifier, to }): JSX.Element => {
    const { scene, loadingScene } = useValues(sceneLogic)
    const activeScene = sceneOverride[loadingScene || scene] || loadingScene || scene

    return (
        <Link to={to}>
            <div
                className={`menu-item${activeScene === identifier ? ' menu-item-active' : ''}`}
                data-attr={`menu-item-${identifier}`}
            >
                {icon}
                <span className="menu-title">{title}</span>
            </div>
        </Link>
    )
}

export const MainNavigation = hot(_MainNavigation)
function _MainNavigation({ sidebarCollapsed, setSidebarCollapsed }): JSX.Element {
    const collapseSidebar = (): void => {
        if (!sidebarCollapsed && window.innerWidth <= 991) {
            setSidebarCollapsed(true)
        }
    }

    useEscapeKey(collapseSidebar, [sidebarCollapsed])

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
                className="navigation-main"
            >
                <div className="navigation-inner">
                    <div className="nav-logo">
                        <img src={smLogo} className="logo-sm" alt="" />
                        <img src={lgLogo} className="logo-lg" alt="" />
                    </div>
                    <MenuItem title="Dashboards" icon={<IconDashboard />} identifier="dashboards" to="/dashboard" />
                    <MenuItem
                        title="Insights"
                        icon={<FundOutlined />}
                        identifier="insights"
                        to="/insights?insight=TRENDS"
                    />
                    <MenuItem title="Persons" icon={<IconPerson />} identifier="persons" to="/persons" />
                </div>
            </Layout.Sider>
        </>
    )
}
