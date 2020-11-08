import React from 'react'
import { Layout } from 'antd'
import { FundOutlined, ProjectFilled, ApiFilled, ClockCircleFilled } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { sceneLogic } from 'scenes/sceneLogic'
import { triggerResizeAfterADelay } from 'lib/utils'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'
import lgLogo from 'public/posthog-logo-white.svg'
import smLogo from 'public/icon-white.svg'
import { hot } from 'react-hot-loader/root'
import './Navigation.scss'
import {
    IconCohorts,
    IconDashboard,
    IconEvents,
    IconFeatureFlags,
    IconFunnel,
    IconInsights,
    IconPerson,
    IconToolbar,
} from './icons'
import { navigationLogic } from './navigationLogic'

// to show the right page in the sidebar
const sceneOverride = {
    action: 'actions',
    person: 'persons',
    dashboard: 'dashboards',
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
                        icon={<IconInsights />}
                        identifier="insights"
                        to="/insights?insight=TRENDS"
                    />
                    <div className="divider" />
                    <MenuItem title="Events" icon={<IconEvents />} identifier="events" to="/events" />
                    <MenuItem title="Sessions" icon={<ClockCircleFilled />} identifier="sessions" to="/sessions" />
                    <div className="divider" />
                    <MenuItem title="Persons" icon={<IconPerson />} identifier="persons" to="/persons" />
                    <MenuItem title="Cohorts" icon={<IconCohorts />} identifier="cohorts" to="/cohorts" />
                    <div className="divider" />
                    <MenuItem
                        title="Feat Flags"
                        icon={<IconFeatureFlags />}
                        identifier="featureFlags"
                        to="/feature_flags"
                    />
                    <div className="divider" />
                    <MenuItem title="Plugins" icon={<ApiFilled />} identifier="plugins" to="/project/plugins" />
                    <MenuItem
                        title="Project"
                        icon={<ProjectFilled />}
                        identifier="projectSettings"
                        to="/project/settings"
                    />
                    <div className="divider" />
                    <MenuItem title="Toolbar" icon={<IconToolbar />} identifier="toolbar" to="/toolbar" />
                </div>
            </Layout.Sider>
        </>
    )
}
