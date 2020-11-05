import React from 'react'
import { Layout } from 'antd'
import { FundOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { sceneLogic } from 'scenes/sceneLogic'
import { triggerResizeAfterADelay } from 'lib/utils'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'
import lgLogo from 'public/posthog-logo-white.svg'
import smLogo from 'public/icon-white.svg'
import { hot } from 'react-hot-loader/root'
import './Navigation.scss'
import { IconDashboard, IconPerson } from './icons'
import { navigationLogic } from './navigationLogic'

// to show the right page in the sidebar
const sceneOverride = {
    action: 'actions',
    person: 'persons',
    dashboard: 'dashboards',
    featureFlags: 'experiments',
}

interface MenuItemProps {
    title: string
    icon: JSX.Element
    identifier: string
    to: string
}

const MenuItem = ({ title, icon, identifier, to }: MenuItemProps): JSX.Element => {
    const { scene, loadingScene } = useValues(sceneLogic)
    const activeScene = sceneOverride[loadingScene || scene] || loadingScene || scene
    const { collapseMenu } = useActions(navigationLogic)

    return (
        <Link to={to} onClick={collapseMenu}>
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
function _MainNavigation(): JSX.Element {
    const { menuCollapsed } = useValues(navigationLogic)
    const { setMenuCollapsed, collapseMenu } = useActions(navigationLogic)

    useEscapeKey(collapseMenu, [menuCollapsed])

    return (
        <>
            <div className={`navigation-mobile-overlay${!menuCollapsed ? ' open' : ''}`} onClick={collapseMenu} />

            <Layout.Sider
                breakpoint="lg"
                collapsedWidth={0}
                width={80}
                collapsed={menuCollapsed}
                trigger={null}
                onCollapse={(collapsed) => {
                    setMenuCollapsed(collapsed)
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
                    <div className="divider" />
                    <MenuItem title="Persons" icon={<IconPerson />} identifier="persons" to="/persons" />
                </div>
            </Layout.Sider>
        </>
    )
}
