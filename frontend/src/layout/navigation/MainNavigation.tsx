import React, { useRef, useState, useEffect } from 'react'
import { Layout, Modal } from 'antd'
import { ProjectFilled, ApiFilled, ClockCircleFilled, DownOutlined } from '@ant-design/icons'
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
    IconActions,
    IconCohorts,
    IconDashboard,
    IconEvents,
    IconFeatureFlags,
    IconInsights,
    IconPerson,
    IconToolbar,
} from './icons'
import { navigationLogic } from './navigationLogic'
import { ToolbarModal } from '~/layout/ToolbarModal/ToolbarModal'

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
    onClick?: () => void
}

const MenuItem = ({ title, icon, identifier, to, onClick }: MenuItemProps): JSX.Element => {
    const { scene, loadingScene } = useValues(sceneLogic)
    const activeScene = sceneOverride[loadingScene || scene] || loadingScene || scene
    const { collapseMenu } = useActions(navigationLogic)

    const handleClick = (): void => {
        if (onClick) {
            onClick()
        }
        collapseMenu()
    }

    return (
        <Link to={to} onClick={handleClick}>
            <div
                className={`menu-item${activeScene === identifier ? ' menu-item-active' : ''}`}
                data-attr={`menu-item-${identifier}`}
            >
                {icon}
                <span className="menu-title text-center">{title}</span>
            </div>
        </Link>
    )
}

export const MainNavigation = hot(_MainNavigation)
function _MainNavigation(): JSX.Element {
    const { menuCollapsed, toolbarModalOpen } = useValues(navigationLogic)
    const { setMenuCollapsed, collapseMenu, setToolbarModalOpen } = useActions(navigationLogic)
    const navRef = useRef<HTMLDivElement | null>(null)
    const [canScroll, setCanScroll] = useState(false)

    useEscapeKey(collapseMenu, [menuCollapsed])

    const calcCanScroll = (target: HTMLDivElement | null): boolean => {
        return !!target && target.scrollHeight > target.offsetHeight + target.scrollTop + 60 // 60px of offset tolerance
    }

    const handleNavScroll = (e: React.UIEvent<HTMLDivElement>): void => {
        const target = e.target as HTMLDivElement
        setCanScroll(calcCanScroll(target))
    }

    const scrollToBottom = (): void => {
        navRef.current?.scrollTo(0, navRef.current?.scrollHeight)
    }

    useEffect(() => {
        setCanScroll(calcCanScroll(navRef.current))
    }, [navRef])

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
                <div className="navigation-inner" ref={navRef} onScroll={handleNavScroll}>
                    <div className="nav-logo">
                        <Link to="/insights">
                            <img src={smLogo} className="logo-sm" alt="" />
                            <img src={lgLogo} className="logo-lg" alt="" />
                        </Link>
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
                    <MenuItem title="Actions" icon={<IconActions />} identifier="actions" to="/actions" />
                    <MenuItem title="Sessions" icon={<ClockCircleFilled />} identifier="sessions" to="/sessions" />
                    <div className="divider" />
                    <MenuItem title="Persons" icon={<IconPerson />} identifier="persons" to="/persons" />
                    <MenuItem title="Cohorts" icon={<IconCohorts />} identifier="cohorts" to="/cohorts" />
                    <div className="divider" />
                    <MenuItem
                        title="Feat. Flags"
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
                    <MenuItem
                        title="Toolbar"
                        icon={<IconToolbar />}
                        identifier="toolbar"
                        to=""
                        onClick={() => setToolbarModalOpen(true)}
                    />
                    <div className={`scroll-indicator ${canScroll ? '' : 'hide'}`} onClick={scrollToBottom}>
                        <DownOutlined />
                    </div>
                </div>
            </Layout.Sider>

            <Modal
                bodyStyle={{ padding: 0 }}
                visible={toolbarModalOpen}
                footer={null}
                onCancel={() => setToolbarModalOpen(false)}
            >
                <ToolbarModal />
            </Modal>
        </>
    )
}
