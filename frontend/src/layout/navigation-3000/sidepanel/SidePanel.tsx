import './SidePanel.scss'

import { IconEllipsis, IconFeatures, IconGear, IconInfo, IconNotebook, IconSupport } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItems, LemonModal } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { resizerLogic, ResizerLogicProps } from 'lib/components/Resizer/resizerLogic'
import { useEffect, useRef } from 'react'
import { NotebookPanel } from 'scenes/notebooks/NotebookPanel/NotebookPanel'

import { SidePanelTab } from '~/types'

import { SidePanelActivation, SidePanelActivationIcon } from './panels/activation/SidePanelActivation'
import { SidePanelActivity, SidePanelActivityIcon } from './panels/activity/SidePanelActivity'
import { SidePanelDiscussion, SidePanelDiscussionIcon } from './panels/discussion/SidePanelDiscussion'
import { SidePanelDocs } from './panels/SidePanelDocs'
import { SidePanelFeaturePreviews } from './panels/SidePanelFeaturePreviews'
import { SidePanelSettings } from './panels/SidePanelSettings'
import { SidePanelStatus, SidePanelStatusIcon } from './panels/SidePanelStatus'
import { SidePanelSupport } from './panels/SidePanelSupport'
import { sidePanelLogic } from './sidePanelLogic'
import { sidePanelStateLogic } from './sidePanelStateLogic'

export const SIDE_PANEL_TABS: Record<
    SidePanelTab,
    { label: string; Icon: any; Content: any; noModalSupport?: boolean }
> = {
    [SidePanelTab.Notebooks]: {
        label: 'Notebooks',
        Icon: IconNotebook,
        Content: NotebookPanel,
        noModalSupport: true,
    },
    [SidePanelTab.Support]: {
        label: 'Support',
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

    [SidePanelTab.FeaturePreviews]: {
        label: 'Feature previews',
        Icon: IconFeatures,
        Content: SidePanelFeaturePreviews,
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
    [SidePanelTab.Status]: {
        label: 'System status',
        Icon: SidePanelStatusIcon,
        Content: SidePanelStatus,
        noModalSupport: true,
    },
}

const DEFAULT_WIDTH = 512

export function SidePanel(): JSX.Element | null {
    const { visibleTabs, extraTabs } = useValues(sidePanelLogic)
    const { selectedTab, sidePanelOpen, modalMode } = useValues(sidePanelStateLogic)
    const { openSidePanel, closeSidePanel, setSidePanelAvailable } = useActions(sidePanelStateLogic)

    const activeTab = sidePanelOpen && selectedTab

    const PanelConent = activeTab ? SIDE_PANEL_TABS[activeTab]?.Content : null

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

    const { desiredWidth, isResizeInProgress } = useValues(resizerLogic(resizerLogicProps))

    useEffect(() => {
        setSidePanelAvailable(true)
        return () => {
            setSidePanelAvailable(false)
        }
    }, [])

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
                isOpen={!!PanelConent && supportsModal}
                onClose={closeSidePanel}
                hideCloseButton
                width="40rem"
            >
                {PanelConent ? <PanelConent /> : null}
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
                width: sidePanelOpenAndAvailable ? desiredWidth ?? DEFAULT_WIDTH : undefined,
            }}
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
            <Resizer {...resizerLogicProps} offset="3rem" />

            {PanelConent ? (
                <div className="SidePanel3000__content">
                    <PanelConent />
                </div>
            ) : null}
        </div>
    )
}
