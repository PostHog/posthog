import './SidePanel.scss'

import { useActions, useValues } from 'kea'
import { lazy, Suspense, useEffect, useRef } from 'react'

import { IconGear, IconLock, IconLogomark, IconNotebook } from '@posthog/icons'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { cn } from 'lib/utils/css-classes'

const NotebookPanel = lazy(() =>
    import('scenes/notebooks/NotebookPanel/NotebookPanel').then((m) => ({ default: m.NotebookPanel }))
)

import { useWindowSize } from 'lib/hooks/useWindowSize'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { SidePanelTab } from '~/types'

import { SidePanelSupportIcon } from 'products/conversations/frontend/components/SidePanel/SidePanelSupportIcon'

import { SidePanelAccessControl } from './panels/access_control/SidePanelAccessControl'
import { SidePanelActivity, SidePanelActivityIcon } from './panels/activity/SidePanelActivity'
import { SidePanelDiscussion, SidePanelDiscussionIcon } from './panels/discussion/SidePanelDiscussion'
import { SidePanelExports, SidePanelExportsIcon } from './panels/exports/SidePanelExports'
import { SidePanelInfo, SidePanelInfoIcon } from './panels/info/SidePanelInfo'
import { SidePanelMax } from './panels/max/SidePanelMax'
import { SidePanelSettings } from './panels/settings/SidePanelSettings'
import { SidePanelSupport } from './panels/support/SidePanelSupport'
import { sidePanelLogic } from './sidePanelLogic'
import { SidePanelNavigation } from './SidePanelNavigation'
import { sidePanelStateLogic } from './sidePanelStateLogic'

export const SIDE_PANEL_TABS: Record<SidePanelTab, { label: string; Icon: any; Content: any }> = {
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
        label: 'Support',
        Icon: SidePanelSupportIcon,
        Content: SidePanelSupport,
    },
    [SidePanelTab.Settings]: {
        label: 'Settings',
        Icon: IconGear,
        Content: SidePanelSettings,
    },
    [SidePanelTab.Exports]: {
        label: 'Exports',
        Icon: SidePanelExportsIcon,
        Content: SidePanelExports,
    },
    [SidePanelTab.Activity]: {
        label: 'Activity logs',
        Icon: SidePanelActivityIcon,
        Content: SidePanelActivity,
    },
    [SidePanelTab.Discussion]: {
        label: 'Discuss',
        Icon: SidePanelDiscussionIcon,
        Content: SidePanelDiscussion,
    },
    [SidePanelTab.AccessControl]: {
        label: 'Access',
        Icon: IconLock,
        Content: SidePanelAccessControl,
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
    const { enabledTabs, visibleTabs } = useValues(sidePanelLogic)
    const { selectedTab, sidePanelOpen } = useValues(sidePanelStateLogic)
    const { openSidePanel, closeSidePanel, setSidePanelAvailable } = useActions(sidePanelStateLogic)

    const activeTab = sidePanelOpen && selectedTab

    // Use enabledTabs (not visibleTabs) so programmatically-opened tabs like Support render
    const PanelContent = activeTab && enabledTabs.includes(activeTab) ? SIDE_PANEL_TABS[activeTab]?.Content : null

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

    const sidePanelOpenAndAvailable = selectedTab && sidePanelOpen && enabledTabs.includes(selectedTab)

    // If the selected tab is no longer available (e.g. navigating away from a scene
    // with Settings or Info), fall back to Info or Max instead of closing
    useEffect(() => {
        if (sidePanelOpen && selectedTab && !sidePanelOpenAndAvailable) {
            const fallbackTab = enabledTabs.includes(SidePanelTab.Info) ? SidePanelTab.Info : SidePanelTab.Max
            openSidePanel(fallbackTab)
        }
    }, [sidePanelOpen, selectedTab, sidePanelOpenAndAvailable, enabledTabs, openSidePanel])

    const { windowSize } = useWindowSize()

    const rawSidePanelWidth = !visibleTabs.length
        ? 0
        : sidePanelOpenAndAvailable
          ? Math.max(desiredSize ?? DEFAULT_WIDTH, SIDE_PANEL_MIN_WIDTH_COMPACT)
          : 0

    const sidePanelWidth = windowSize.width != null ? Math.min(rawSidePanelWidth, windowSize.width) : rawSidePanelWidth

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
                        <Suspense fallback={<Spinner className="text-4xl mx-auto mt-16" />}>
                            <PanelContent />
                        </Suspense>
                    </ErrorBoundary>
                </SidePanelNavigation>
            )}
        </div>
    )
}
