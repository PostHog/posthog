import './SidePanel.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconBook, IconGear, IconInfo, IconLock, IconLogomark, IconNotebook } from '@posthog/icons'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { cn } from 'lib/utils/css-classes'
import { NotebookPanel } from 'scenes/notebooks/NotebookPanel/NotebookPanel'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import {
    SidePanelExports,
    SidePanelExportsIcon,
} from '~/layout/navigation-3000/sidepanel/panels/exports/SidePanelExports'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { SidePanelTab } from '~/types'

import { SidePanelSupportIcon } from 'products/conversations/frontend/components/SidePanel/SidePanelSupportIcon'

import { SidePanelNavigation } from './SidePanelNavigation'
import { SidePanelChangelog } from './panels/SidePanelChangelog'
import { SidePanelDocs } from './panels/SidePanelDocs'
import { SidePanelHealth, SidePanelHealthIcon } from './panels/SidePanelHealth'
import { SidePanelInfo, SidePanelInfoIcon } from './panels/SidePanelInfo'
import { SidePanelMax } from './panels/SidePanelMax'
import { SidePanelSdkDoctor, SidePanelSdkDoctorIcon } from './panels/SidePanelSdkDoctor'
import { SidePanelSettings } from './panels/SidePanelSettings'
import { SidePanelStatus, SidePanelStatusIcon } from './panels/SidePanelStatus'
import { SidePanelSupport } from './panels/SidePanelSupport'
import { SidePanelAccessControl } from './panels/access_control/SidePanelAccessControl'
import { SidePanelActivity, SidePanelActivityIcon } from './panels/activity/SidePanelActivity'
import { SidePanelDiscussion, SidePanelDiscussionIcon } from './panels/discussion/SidePanelDiscussion'
import { sidePanelLogic } from './sidePanelLogic'
import { sidePanelStateLogic } from './sidePanelStateLogic'

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
    },
    [SidePanelTab.Support]: {
        label: 'Help',
        Icon: SidePanelSupportIcon,
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
    [SidePanelTab.Info]: {
        label: 'Actions',
        Icon: SidePanelInfoIcon,
        Content: SidePanelInfo,
    },
}

const DEFAULT_WIDTH = 512
const SIDE_PANEL_MIN_WIDTH_COMPACT = 330

export function SidePanel({ className }: { className?: string }): JSX.Element | null {
    const { theme } = useValues(themeLogic)
    const { visibleTabs } = useValues(sidePanelLogic)
    const { selectedTab, sidePanelOpen } = useValues(sidePanelStateLogic)
    const { openSidePanel, closeSidePanel, setSidePanelAvailable } = useActions(sidePanelStateLogic)
    const { scenePanelIsPresent } = useValues(sceneLayoutLogic)

    const activeTab = sidePanelOpen && selectedTab

    const isInfoTabActive = activeTab === SidePanelTab.Info && scenePanelIsPresent
    const PanelContent =
        activeTab && (visibleTabs.includes(activeTab) || isInfoTabActive) ? SIDE_PANEL_TABS[activeTab]?.Content : null

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

    const sidePanelOpenAndAvailable =
        selectedTab &&
        sidePanelOpen &&
        (visibleTabs.includes(selectedTab) || (selectedTab === SidePanelTab.Info && scenePanelIsPresent))
    const sidePanelWidth = !visibleTabs.length
        ? 0
        : sidePanelOpenAndAvailable
          ? Math.max(desiredSize ?? DEFAULT_WIDTH, SIDE_PANEL_MIN_WIDTH_COMPACT)
          : 0

    // Update sidepanel width in panelLayoutLogic
    useEffect(() => {
        setSidePanelWidth(sidePanelWidth)
    }, [sidePanelWidth, setSidePanelWidth])

    if (!visibleTabs.length) {
        return null
    }

    return (
        <div
            className={cn(
                'SidePanel3000 h-screen',
                sidePanelOpenAndAvailable && 'SidePanel3000--open justify-end',
                isResizeInProgress && 'SidePanel3000--resizing',
                '@container/side-panel bg-surface-secondary absolute top-0 right-0 bottom-0 h-full flex flex-col border-t-none',
                !sidePanelOpen && 'hidden',
                className
            )}
            ref={ref}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    width: sidePanelOpenAndAvailable ? sidePanelWidth : '0px',
                    '--side-panel-min-width': `${SIDE_PANEL_MIN_WIDTH_COMPACT}px`,
                    ...theme?.sidebarStyle,
                } as React.CSSProperties
            }
            id="side-panel"
        >
            {sidePanelOpenAndAvailable && (
                <>
                    <Resizer
                        {...resizerLogicProps}
                        className={cn('top-[calc(var(--scene-layout-header-height)+8px)] left-[-1px] bottom-4', {
                            'left-0': sidePanelOpenAndAvailable,
                            'top-0 h-full': sidePanelOpenAndAvailable,
                        })}
                    />
                    {/* Overlay for mobile to click outside to close the side panel */}
                    <div onClick={() => closeSidePanel()} className="lg:hidden fixed inset-0 -z-1" />
                </>
            )}

            {PanelContent && (
                <SidePanelNavigation activeTab={activeTab as SidePanelTab} onTabChange={(tab) => openSidePanel(tab)}>
                    <ErrorBoundary>
                        <PanelContent />
                    </ErrorBoundary>
                </SidePanelNavigation>
            )}
        </div>
    )
}
