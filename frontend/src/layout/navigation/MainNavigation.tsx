import React, { useEffect, useRef, useState } from 'react'
import { Layout, Menu, Modal, Popover, Tooltip } from 'antd'
import {
    ApiFilled,
    ClockCircleFilled,
    DownOutlined,
    HomeOutlined,
    MessageOutlined,
    PlusOutlined,
    ProjectFilled,
    PushpinFilled,
    SettingOutlined,
} from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { Scene, sceneLogic, urls } from 'scenes/sceneLogic'
import { isMobile } from 'lib/utils'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'
import lgLogo from 'public/posthog-logo-white.svg'
import smLogo from 'public/icon-white.svg'
import './Navigation.scss'
import {
    IconCohorts,
    IconDashboard,
    IconEvents,
    IconFeatureFlags,
    IconInsights,
    IconPerson,
    IconToolbar,
} from 'lib/components/icons'
import { navigationLogic } from './navigationLogic'
import { ToolbarModal } from '~/layout/ToolbarModal/ToolbarModal'
import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardType, HotKeys, ViewType } from '~/types'
import { userLogic } from 'scenes/userLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { canViewPlugins } from 'scenes/plugins/access'
import { useGlobalKeyboardHotkeys, useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { router } from 'kea-router'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { FEATURE_FLAGS } from 'lib/constants'

// to show the right page in the sidebar
const sceneOverride: Partial<Record<Scene, string>> = {
    action: 'actions',
    person: 'persons',
    dashboard: 'dashboards',
}

interface MenuItemProps {
    title: string
    icon: JSX.Element
    identifier: string
    to: string
    hotkey?: HotKeys
    tooltip?: string
    onClick?: () => void
}

const MenuItem = ({ title, icon, identifier, to, hotkey, tooltip, onClick }: MenuItemProps): JSX.Element => {
    const { activeScene } = useValues(sceneLogic)
    const { hotkeyNavigationEngaged } = useValues(navigationLogic)
    const { collapseMenu, setHotkeyNavigationEngaged } = useActions(navigationLogic)
    const { push } = useActions(router)
    const { reportHotkeyNavigation } = useActions(eventUsageLogic)

    const isActive = activeScene && identifier === (sceneOverride[activeScene] || activeScene)

    function handleClick(): void {
        onClick?.()
        collapseMenu()
        setHotkeyNavigationEngaged(false)
    }

    useKeyboardHotkeys(
        hotkeyNavigationEngaged && hotkey
            ? {
                  [hotkey]: {
                      action: () => {
                          handleClick()
                          if (to) {
                              push(to)
                          }
                          reportHotkeyNavigation('global', hotkey)
                      },
                  },
              }
            : {},
        undefined,
        true
    )

    return (
        <Link to={to} onClick={handleClick}>
            <Tooltip
                title={
                    tooltip && !isMobile() ? (
                        <>
                            <div className="mb-025">
                                <b>{title}</b>
                                {hotkey && (
                                    <>
                                        <span className="hotkey menu-tooltip-hotkey">G</span>
                                        <span className="hotkey-plus" />
                                        <span className="hotkey menu-tooltip-hotkey">{hotkey.toUpperCase()}</span>
                                    </>
                                )}
                            </div>
                            {tooltip}
                        </>
                    ) : undefined
                }
                placement="left"
            >
                <div
                    className={`menu-item${isActive ? ' menu-item-active' : ''}`}
                    data-attr={`menu-item-${identifier}`}
                >
                    {icon}
                    <span className="menu-title text-center">{title}</span>
                    {hotkey && (
                        <span className={`hotkey${hotkeyNavigationEngaged ? '' : ' hide'}`}>
                            {hotkey.toUpperCase()}
                        </span>
                    )}
                </div>
            </Tooltip>
        </Link>
    )
}

function PinnedDashboards(): JSX.Element {
    const { pinnedDashboards, dashboards } = useValues(dashboardsModel)
    const { setPinnedDashboardsVisible } = useActions(navigationLogic)

    return (
        <Menu className="pinned-dashboards">
            {dashboards.length ? (
                <>
                    {pinnedDashboards.length && (
                        <Menu.ItemGroup title="Pinned dashboards" key="pinned">
                            {pinnedDashboards.map((item: DashboardType, index: number) => (
                                <Menu.Item key={`pinned-${item.id}`} style={{ margin: 0 }}>
                                    <MenuItem
                                        title={item.name}
                                        icon={<PushpinFilled />}
                                        identifier={`dashboard-${index}`}
                                        to={urls.dashboard(item.id)}
                                        onClick={() => setPinnedDashboardsVisible(false)}
                                    />
                                </Menu.Item>
                            ))}
                        </Menu.ItemGroup>
                    )}
                    {dashboards.length > pinnedDashboards.length && (
                        <Menu.ItemGroup title="All dashboards" key="all" className="all-dashboard-list">
                            {dashboards
                                .filter((item: DashboardType) => !item.pinned)
                                .map((item: DashboardType) => (
                                    <Menu.Item key={`dashboard-${item.id}`} style={{ margin: 0 }}>
                                        <MenuItem
                                            title={item.name}
                                            icon={<IconDashboard />}
                                            identifier={`dashboard-${item.id}`}
                                            to={urls.dashboard(item.id)}
                                            onClick={() => setPinnedDashboardsVisible(false)}
                                        />
                                    </Menu.Item>
                                ))}
                        </Menu.ItemGroup>
                    )}
                </>
            ) : (
                <Menu.Item className="text-center" style={{ height: 'initial' }}>
                    <span className="text-muted">You don't have any dashboards yet.</span>
                    <div>
                        <Link
                            to={[urls.dashboards(), '?new']}
                            style={{ color: 'var(--primary)' }}
                            data-attr="create-dashboard-pinned-overlay"
                        >
                            <PlusOutlined />
                            Create your first dashboard now
                        </Link>
                    </div>
                </Menu.Item>
            )}
        </Menu>
    )
}

export function MainNavigation(): JSX.Element {
    const { user } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { menuCollapsed, toolbarModalOpen, pinnedDashboardsVisible, hotkeyNavigationEngaged } = useValues(
        navigationLogic
    )
    const {
        setMenuCollapsed,
        collapseMenu,
        setToolbarModalOpen,
        setPinnedDashboardsVisible,
        setHotkeyNavigationEngaged,
    } = useActions(navigationLogic)
    const navRef = useRef<HTMLDivElement | null>(null)
    const [canScroll, setCanScroll] = useState(false)
    const { featureFlags } = useValues(featureFlagLogic)

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

    useGlobalKeyboardHotkeys({ g: { action: () => setHotkeyNavigationEngaged(!hotkeyNavigationEngaged) } })

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
                }}
                className="navigation-main"
            >
                <div className="navigation-inner" ref={navRef} onScroll={handleNavScroll}>
                    <div className="nav-logo">
                        {
                            <Link to={urls.insights()}>
                                <img src={smLogo} className="logo-sm" alt="" />
                                <img src={lgLogo} className="logo-lg" alt="" />
                            </Link>
                        }
                    </div>
                    {currentOrganization?.setup.is_active && (
                        <MenuItem
                            title="Setup"
                            icon={<SettingOutlined />}
                            identifier="onboardingSetup"
                            to={urls.onboardingSetup()}
                            hotkey="u"
                        />
                    )}
                    {featureFlags[FEATURE_FLAGS.PROJECT_HOME] && (
                        <MenuItem title="Home" icon={<HomeOutlined />} identifier="home" to={urls.home()} />
                    )}
                    <MenuItem
                        title="Insights"
                        icon={<IconInsights />}
                        identifier="insights"
                        to={urls.insightView(ViewType.TRENDS)}
                        hotkey="i"
                        tooltip="Answers to all your analytics questions."
                    />
                    <Popover
                        content={PinnedDashboards}
                        placement="right"
                        trigger="hover"
                        arrowPointAtCenter
                        overlayClassName="pinned-dashboards-popover"
                        onVisibleChange={(visible) => setPinnedDashboardsVisible(visible)}
                        visible={pinnedDashboardsVisible}
                    >
                        <div>
                            <MenuItem
                                title="Dashboards"
                                icon={<IconDashboard />}
                                identifier="dashboards"
                                to={urls.dashboards()}
                                onClick={() => setPinnedDashboardsVisible(false)}
                                hotkey="d"
                            />
                        </div>
                    </Popover>

                    <div className="divider" />
                    <MenuItem
                        title="Events"
                        icon={<IconEvents />}
                        identifier="events"
                        to={urls.events()}
                        hotkey="e"
                        tooltip="List of events and actions"
                    />
                    <MenuItem
                        title="Sessions"
                        icon={<ClockCircleFilled />}
                        identifier="sessions"
                        to={urls.sessions()}
                        hotkey="s"
                        tooltip="Understand interactions based by visits and watch session recordings"
                    />
                    <div className="divider" />
                    <MenuItem
                        title="Persons"
                        icon={<IconPerson />}
                        identifier="persons"
                        to={urls.persons()}
                        hotkey="p"
                        tooltip="Understand your users individually"
                    />
                    <MenuItem
                        title="Cohorts"
                        icon={<IconCohorts />}
                        identifier="cohorts"
                        to={urls.cohorts()}
                        hotkey="c"
                        tooltip="Group users for easy filtering"
                    />
                    <div className="divider" />
                    <MenuItem
                        title="Feat. Flags"
                        icon={<IconFeatureFlags />}
                        identifier="featureFlags"
                        to={urls.featureFlags()}
                        hotkey="f"
                        tooltip="Controlled feature releases"
                    />
                    <div className="divider" />
                    {canViewPlugins(user?.organization) && (
                        <MenuItem
                            title="Plugins"
                            icon={<ApiFilled />}
                            identifier="plugins"
                            to={urls.plugins()}
                            hotkey="l"
                            tooltip="Extend your analytics functionality"
                        />
                    )}
                    <MenuItem
                        title="Annotations"
                        icon={<MessageOutlined />}
                        identifier="annotations"
                        to={urls.annotations()}
                        hotkey="a"
                    />
                    <MenuItem
                        title="Project"
                        icon={<ProjectFilled />}
                        identifier="projectSettings"
                        to={urls.projectSettings()}
                        hotkey="j"
                    />
                    <div className="divider" />
                    <MenuItem
                        title="Toolbar"
                        icon={<IconToolbar />}
                        identifier="toolbar"
                        to=""
                        hotkey="t"
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
