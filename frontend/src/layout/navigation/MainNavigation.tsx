import React from 'react'
import { Layout } from 'antd'
import { FundOutlined } from '@ant-design/icons'
import { useValues } from 'kea'
import { sceneLogic } from 'scenes/sceneLogic'
import { triggerResizeAfterADelay } from 'lib/utils'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'
import whiteLogo from 'public/posthog-logo-white.svg'
import { hot } from 'react-hot-loader/root'
import './Navigation.scss'
import { IconDashboard, IconPerson } from './icons'

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

const MenuItem = ({ title, icon, identifier }): JSX.Element => {
    const { scene, loadingScene } = useValues(sceneLogic)
    const activeScene = sceneOverride[loadingScene || scene] || loadingScene || scene

    return (
        <div
            className={`menu-item${activeScene === identifier ? ' menu-item-active' : ''}`}
            data-attr={`menu-item-${identifier}`}
        >
            {icon}
            <span className="menu-title">{title}</span>
        </div>
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
                style={{ backgroundColor: 'var(--bg-menu)' }}
            >
                <div className="navigation-main">
                    <Logo />
                    <MenuItem title="Insights" icon={<IconDashboard />} identifier="insights" />
                    <MenuItem title="Persons" icon={<IconPerson />} identifier="persons" />
                    <MenuItem title="Dashboards" icon={<FundOutlined />} identifier="dashboards" />
                </div>
            </Layout.Sider>
        </>
    )
}
