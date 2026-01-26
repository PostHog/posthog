import './SidePanel.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import {
    IconBook,
    IconEllipsis,
    IconGear,
    IconInfo,
    IconLock,
    IconLogomark,
    IconNotebook,
    IconSupport,
} from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItems, LemonModal } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'
import { NotebookPanel } from 'scenes/notebooks/NotebookPanel/NotebookPanel'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import {
    SidePanelExports,
    SidePanelExportsIcon,
} from '~/layout/navigation-3000/sidepanel/panels/exports/SidePanelExports'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { SidePanelTab } from '~/types'

import { SidePanelChangelog } from './panels/SidePanelChangelog'
import { SidePanelDocs } from './panels/SidePanelDocs'
import { SidePanelHealth, SidePanelHealthIcon } from './panels/SidePanelHealth'
import { SidePanelMax } from './panels/SidePanelMax'
import { SidePanelSdkDoctor, SidePanelSdkDoctorIcon } from './panels/SidePanelSdkDoctor'
import { SidePanelSettings } from './panels/SidePanelSettings'
import { SidePanelStatus, SidePanelStatusIcon } from './panels/SidePanelStatus'
import { SidePanelSupport } from './panels/SidePanelSupport'
import { SidePanelAccessControl } from './panels/access_control/SidePanelAccessControl'
import { SidePanelActivation, SidePanelActivationIcon } from './panels/activation/SidePanelActivation'
import { SidePanelActivity, SidePanelActivityIcon } from './panels/activity/SidePanelActivity'
import { SidePanelDiscussion, SidePanelDiscussionIcon } from './panels/discussion/SidePanelDiscussion'
import { sidePanelLogic } from './sidePanelLogic'
import { sidePanelStateLogic } from './sidePanelStateLogic'

const SIDE_PANEL_TAB_KEYBINDS: Partial<Record<SidePanelTab, string[][]>> = {
    [SidePanelTab.Max]: [['command', 'option', 'a']],
    [SidePanelTab.Support]: [['command', 'option', 'h']],
}

export const SIDE_PANEL_TABS: Record<
    SidePanelTab,
    { label: string; Icon: any; Content: any; noModalSupport?: boolean }
> = {
    [SidePanelTab.Max]: {
        label: 'PostHog AI',
        Icon: IconLogomark,
        Content: SidePanelMax,
    },
    [SidePanelTab.Notebooks]: {
        label: 'Notebooks',
        Icon: IconNotebook,
        Content: NotebookPanel,
        noModalSupport: true,
    },
    [SidePanelTab.Support]: {
        label: 'Help',
        Icon: IconSupport,
        Content: SidePanelSupport,
    },
    [SidePanelTab.Docs]: {
        label: 'Docs',
        Icon: IconInfo,
        Content: SidePanelDocs,
        noModalSupport: true,
    },
    [SidePanelTab.Changelog]: {
        label: 'Changelog',
        Icon: IconBook,
        Content: SidePanelChangelog,
        noModalSupport: true,
    },

    [SidePanelTab.Activation]: {
        label: 'Quick start',
        Icon: SidePanelActivationIcon,
        Content: SidePanelActivation,
    },
    [SidePanelTab.Settings]: {
        label: 'Settings',
        Icon: IconGear,
        Content: SidePanelSettings,
    },

    [SidePanelTab.Activity]: {
        label: 'Team activity',
        Icon: SidePanelActivityIcon,
        Content: SidePanelActivity,
    },
    [SidePanelTab.Discussion]: {
        label: 'Discussion',
        Icon: SidePanelDiscussionIcon,
        Content: SidePanelDiscussion,
    },
    [SidePanelTab.Exports]: {
        label: 'Exports',
        Icon: SidePanelExportsIcon,
        Content: SidePanelExports,
    },
    [SidePanelTab.Status]: {
        label: 'System status',
        Icon: SidePanelStatusIcon,
        Content: SidePanelStatus,
        noModalSupport: true,
    },
    [SidePanelTab.AccessControl]: {
        label: 'Access control',
        Icon: IconLock,
        Content: SidePanelAccessControl,
    },
    [SidePanelTab.SdkDoctor]: {
        label: 'SDK Doctor',
        Icon: SidePanelSdkDoctorIcon,
        Content: SidePanelSdkDoctor,
    },
    [SidePanelTab.Health]: {
        label: 'Pipeline status',
        Icon: SidePanelHealthIcon,
        Content: SidePanelHealth,
    },
}

const DEFAULT_WIDTH = 512
const SIDE_PANEL_BAR_WIDTH = 40
const SIDE_PANEL_MIN_WIDTH = 448 // Match --side-panel-min-width (28rem)

export function SidePanel({
    className,
    contentClassName,
}: {
    className?: string
    contentClassName?: string
}): JSX.Element | null {
    const { theme } = useValues(themeLogic)
    const { visibleTabs, extraTabs } = useValues(sidePanelLogic)
    const { selectedTab, sidePanelOpen, modalMode } = useValues(sidePanelStateLogic)
    const { openSidePanel, closeSidePanel, setSidePanelAvailable } = useActions(sidePanelStateLogic)
    const isRemovingSidePanelFlag = useFeatureFlag('UX_REMOVE_SIDEPANEL')

    const activeTab = sidePanelOpen && selectedTab

    const PanelContent = activeTab && visibleTabs.includes(activeTab) ? SIDE_PANEL_TABS[activeTab]?.Content : null

    const ref = useRef<HTMLDivElement>(null)

    const resizerLogicProps: ResizerLogicProps = {
        containerRef: ref,
        logicKey: 'side-panel',
        persistent: true,
        closeThreshold: 200,
        placement: 'left',
        onToggleClosed: (shouldBeClosed) => {
            shouldBeClosed ? closeSidePanel() : selectedTab ? openSidePanel(selectedTab) : undefined
        },
    }

    const { desiredSize, isResizeInProgress } = useValues(resizerLogic(resizerLogicProps))
    const { setMainContentRect, setSidePanelWidth } = useActions(panelLayoutLogic)
    const { mainContentRef } = useValues(panelLayoutLogic)

    useEffect(() => {
        setSidePanelAvailable(true)
        return () => {
            setSidePanelAvailable(false)
        }
    }, [setSidePanelAvailable])

    // Trigger scene width recalculation when SidePanel size changes
    useEffect(() => {
        if (mainContentRef?.current) {
            setMainContentRect(mainContentRef.current.getBoundingClientRect())
        }
    }, [desiredSize, sidePanelOpen, setMainContentRect, mainContentRef])

    const sidePanelOpenAndAvailable = selectedTab && sidePanelOpen && visibleTabs.includes(selectedTab)
    const sidePanelWidth = !visibleTabs.length
        ? 0
        : sidePanelOpenAndAvailable
          ? Math.max(desiredSize ?? DEFAULT_WIDTH, SIDE_PANEL_MIN_WIDTH)
          : SIDE_PANEL_BAR_WIDTH

    // Update sidepanel width in panelLayoutLogic
    useEffect(() => {
        setSidePanelWidth(sidePanelWidth)
    }, [sidePanelWidth, setSidePanelWidth])

    if (!visibleTabs.length) {
        return null
    }

    const menuOptions: LemonMenuItems | undefined = extraTabs
        ? [
              {
                  title: 'Open in side panel',
                  items: extraTabs.map((tab) => {
                      const { Icon, label } = SIDE_PANEL_TABS[tab]

                      return {
                          label: label,
                          icon: <Icon />,
                          onClick: () => openSidePanel(tab),
                      }
                  }),
              },
          ]
        : undefined

    if (modalMode) {
        const supportsModal = activeTab ? !SIDE_PANEL_TABS[activeTab]?.noModalSupport : true
        return (
            <LemonModal
                simple
                isOpen={!!PanelContent && supportsModal}
                onClose={closeSidePanel}
                hideCloseButton
                width="40rem"
            >
                {PanelContent ? <PanelContent /> : null}
            </LemonModal>
        )
    }

    return (
        <div
            className={cn(
                'SidePanel3000 h-screen',
                sidePanelOpenAndAvailable && 'SidePanel3000--open justify-end',
                isResizeInProgress && 'SidePanel3000--resizing',
                isRemovingSidePanelFlag && 'bg-surface-tertiary',
                className
            )}
            ref={ref}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: isRemovingSidePanelFlag ? (sidePanelOpenAndAvailable ? sidePanelWidth : '0px') : sidePanelWidth,
                ...theme?.sidebarStyle,
            }}
            id="side-panel"
        >
            {sidePanelOpenAndAvailable && (
                <Resizer
                    {...resizerLogicProps}
                    className={cn('top-[calc(var(--scene-layout-header-height)+8px)] left-[-1px] bottom-4', {
                        'left-0': sidePanelOpenAndAvailable,
                        // Hide handle line, make it as thick as the gap between scene and sidepanel (looking like split-screen, nice.)
                        '-left-[3.5px] [&_*:before]:hidden [&_*:after]:w-[2px] [--resizer-thickness:12px]':
                            sidePanelOpenAndAvailable && isRemovingSidePanelFlag,
                    })}
                />
            )}

            {!isRemovingSidePanelFlag && (
                <div className="SidePanel3000__bar">
                    <div className="SidePanel3000__tabs">
                        <div className="SidePanel3000__tabs-content">
                            {visibleTabs.map((tab: SidePanelTab) => {
                                const { Icon, label } = SIDE_PANEL_TABS[tab]
                                const keybind = SIDE_PANEL_TAB_KEYBINDS[tab]

                                const button = (
                                    <LemonButton
                                        key={tab}
                                        icon={<Icon className="size-5" />}
                                        onClick={() =>
                                            activeTab === tab ? closeSidePanel() : openSidePanel(tab as SidePanelTab)
                                        }
                                        data-attr={`sidepanel-tab-${tab}`}
                                        data-ph-capture-attribute-state-before-click={
                                            activeTab === tab ? 'open' : 'closed'
                                        }
                                        active={activeTab === tab}
                                        type="secondary"
                                        status="alt"
                                        tooltip={label}
                                        size="xsmall"
                                    >
                                        {label}
                                    </LemonButton>
                                )

                                if (keybind) {
                                    return (
                                        <AppShortcut
                                            key={tab}
                                            name={`SidePanel-${tab}`}
                                            keybind={keybind}
                                            intent={`Open ${label}`}
                                            priority={label === 'PostHog AI' ? 10 : 0}
                                            interaction="click"
                                        >
                                            {button}
                                        </AppShortcut>
                                    )
                                }

                                return button
                            })}
                        </div>
                    </div>
                    {menuOptions ? (
                        <div className="shrink-0 flex items-center m-2">
                            <LemonMenu items={menuOptions}>
                                <LemonButton size="small" icon={<IconEllipsis />} />
                            </LemonMenu>
                        </div>
                    ) : null}
                </div>
            )}

            {PanelContent ? (
                <div
                    className={cn('SidePanel3000__content', contentClassName, {
                        'border-l-0': isRemovingSidePanelFlag,
                    })}
                >
                    <ErrorBoundary>
                        <PanelContent />
                    </ErrorBoundary>
                </div>
            ) : null}
        </div>
    )
}
