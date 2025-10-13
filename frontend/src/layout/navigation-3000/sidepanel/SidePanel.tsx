import './SidePanel.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconEllipsis, IconGear, IconInfo, IconLock, IconNotebook, IconSupport } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItems, LemonModal, ProfilePicture } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { NotebookPanel } from 'scenes/notebooks/NotebookPanel/NotebookPanel'
import { userLogic } from 'scenes/userLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import {
    SidePanelExports,
    SidePanelExportsIcon,
} from '~/layout/navigation-3000/sidepanel/panels/exports/SidePanelExports'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { SidePanelTab } from '~/types'

import { SidePanelDocs } from './panels/SidePanelDocs'
import { SidePanelMax } from './panels/SidePanelMax'
import { SidePanelSettings } from './panels/SidePanelSettings'
import { SidePanelStatus, SidePanelStatusIcon } from './panels/SidePanelStatus'
import { SidePanelSupport } from './panels/SidePanelSupport'
import { SidePanelAccessControl } from './panels/access_control/SidePanelAccessControl'
import { SidePanelActivation, SidePanelActivationIcon } from './panels/activation/SidePanelActivation'
import { SidePanelActivity, SidePanelActivityIcon } from './panels/activity/SidePanelActivity'
import { SidePanelDiscussion, SidePanelDiscussionIcon } from './panels/discussion/SidePanelDiscussion'
import { sidePanelLogic } from './sidePanelLogic'
import { WithinSidePanelContext, sidePanelStateLogic } from './sidePanelStateLogic'

export const SIDE_PANEL_TABS: Record<
    SidePanelTab,
    { label: string; Icon: any; Content: any; noModalSupport?: boolean }
> = {
    [SidePanelTab.Max]: {
        label: 'Max AI',
        Icon: function IconMaxFromHedgehogConfig() {
            const { user } = useValues(userLogic)
            return (
                <ProfilePicture
                    user={{ hedgehog_config: { ...user?.hedgehog_config, use_as_profile: true } }}
                    size="md"
                    className="border bg-bg-light -scale-x-100" // Flip the hedegehog to face the scene
                />
            )
        },
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
}

const DEFAULT_WIDTH = 512

export function SidePanel(): JSX.Element | null {
    const { theme } = useValues(themeLogic)
    const { visibleTabs, extraTabs } = useValues(sidePanelLogic)
    const { selectedTab, sidePanelOpen, modalMode } = useValues(sidePanelStateLogic)
    const { openSidePanel, closeSidePanel, setSidePanelAvailable } = useActions(sidePanelStateLogic)

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
    const { setMainContentRect } = useActions(panelLayoutLogic)
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

    if (!visibleTabs.length) {
        return null
    }

    const sidePanelOpenAndAvailable = selectedTab && sidePanelOpen && visibleTabs.includes(selectedTab)

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
            className={clsx(
                'SidePanel3000',
                sidePanelOpenAndAvailable && 'SidePanel3000--open',
                isResizeInProgress && 'SidePanel3000--resizing'
            )}
            ref={ref}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: sidePanelOpenAndAvailable ? (desiredSize ?? DEFAULT_WIDTH) : undefined,
                ...theme?.sidebarStyle,
            }}
            id="side-panel"
        >
            <Resizer {...resizerLogicProps} />
            <div className="SidePanel3000__bar">
                <div className="SidePanel3000__tabs">
                    <div className="SidePanel3000__tabs-content">
                        {visibleTabs.map((tab: SidePanelTab) => {
                            const { Icon, label } = SIDE_PANEL_TABS[tab]
                            return (
                                <LemonButton
                                    key={tab}
                                    icon={<Icon />}
                                    onClick={() =>
                                        activeTab === tab ? closeSidePanel() : openSidePanel(tab as SidePanelTab)
                                    }
                                    data-attr={`sidepanel-tab-${tab}`}
                                    data-ph-capture-attribute-state-before-click={activeTab === tab ? 'open' : 'closed'}
                                    active={activeTab === tab}
                                    type="secondary"
                                    status="alt"
                                >
                                    {label}
                                </LemonButton>
                            )
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

            {PanelContent ? (
                <div className="SidePanel3000__content">
                    <WithinSidePanelContext.Provider value={true}>
                        <ErrorBoundary>
                            <PanelContent />
                        </ErrorBoundary>
                    </WithinSidePanelContext.Provider>
                </div>
            ) : null}
        </div>
    )
}
