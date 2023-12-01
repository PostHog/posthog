import './SidePanel.scss'

import {
    IconEllipsis,
    IconFeatures,
    IconGear,
    IconInfo,
    IconNotebook,
    IconNotification,
    IconSupport,
} from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { resizerLogic, ResizerLogicProps } from 'lib/components/Resizer/resizerLogic'
import { useEffect, useRef } from 'react'
import { NotebookPanel } from 'scenes/notebooks/NotebookPanel/NotebookPanel'

import { SidePanelTab } from '~/types'

import { SidePanelActivity } from './panels/activity/SidePanelActivity'
import { SidePanelActivation, SidePanelActivationIcon } from './panels/SidePanelActivation'
import { SidePanelDocs } from './panels/SidePanelDocs'
import { SidePanelFeaturePreviews } from './panels/SidePanelFeaturePreviews'
import { SidePanelSettings } from './panels/SidePanelSettings'
import { SidePanelSupport } from './panels/SidePanelSupport'
import { sidePanelLogic } from './sidePanelLogic'
import { sidePanelStateLogic } from './sidePanelStateLogic'

export const SidePanelTabs: Record<SidePanelTab, { label: string; Icon: any; Content: any }> = {
    [SidePanelTab.Notebooks]: {
        label: 'Notebooks',
        Icon: IconNotebook,
        Content: NotebookPanel,
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
        label: 'Previews',
        Icon: IconFeatures,
        Content: SidePanelFeaturePreviews,
    },
    [SidePanelTab.Activity]: {
        label: 'Activity',
        Icon: IconNotification,
        Content: SidePanelActivity,
    },
}

export function SidePanel(): JSX.Element | null {
    const { visibleTabs, extraTabs } = useValues(sidePanelLogic)
    const { selectedTab, sidePanelOpen } = useValues(sidePanelStateLogic)
    const { openSidePanel, closeSidePanel, setSidePanelAvailable } = useActions(sidePanelStateLogic)

    const activeTab = sidePanelOpen && selectedTab

    const PanelConent = activeTab ? SidePanelTabs[activeTab]?.Content : null

    const ref = useRef<HTMLDivElement>(null)

    const resizerLogicProps: ResizerLogicProps = {
        containerRef: ref,
        persistentKey: 'side-panel',
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
                      const { Icon, label } = SidePanelTabs[tab]

                      return {
                          label: label,
                          icon: <Icon />,
                          onClick: () => openSidePanel(tab),
                      }
                  }),
              },
          ]
        : undefined

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
                width: sidePanelOpenAndAvailable ? desiredWidth ?? undefined : undefined,
            }}
        >
            <Resizer {...resizerLogicProps} />
            <div className="SidePanel3000__bar">
                <div className="SidePanel3000__tabs">
                    <div className="SidePanel3000__tabs-content">
                        {visibleTabs.map((tab: SidePanelTab) => {
                            const { Icon, label } = SidePanelTabs[tab]
                            return (
                                <LemonButton
                                    key={tab}
                                    icon={<Icon className="rotate-270 w-6" />}
                                    onClick={() =>
                                        activeTab === tab ? closeSidePanel() : openSidePanel(tab as SidePanelTab)
                                    }
                                    data-attr={`sidepanel-tab-${tab}`}
                                    active={activeTab === tab}
                                    type="secondary"
                                    stealth={true}
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
                            <LemonButton size="small" status="stealth" icon={<IconEllipsis />} />
                        </LemonMenu>
                    </div>
                ) : null}
            </div>
            <Resizer {...resizerLogicProps} offset={'3rem'} />

            {PanelConent ? (
                <div className="SidePanel3000__content">
                    <PanelConent />
                </div>
            ) : null}
        </div>
    )
}
