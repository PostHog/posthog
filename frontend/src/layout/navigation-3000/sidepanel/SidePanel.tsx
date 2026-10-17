import './SidePanel.scss'

import { useActions, useValues } from 'kea'
import { memo, useEffect, useRef } from 'react'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { cn } from 'lib/utils/css-classes'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { TodayContextPanelCard } from '~/layout/today/TodayContextPanelCard'
import { todayShellLogic } from '~/layout/today/todayShellLogic'
import { SidePanelTab } from '~/types'

import { SidePanelContent } from './SidePanelContent'
import { sidePanelLogic } from './sidePanelLogic'
import { sidePanelStateLogic } from './sidePanelStateLogic'
import { SIDE_PANEL_TABS } from './sidePanelTabs'

const DEFAULT_WIDTH = 512
const SIDE_PANEL_MIN_WIDTH_COMPACT = 330
// The framed Today layout gives the panel its own column, so a wider panel takes the space from the scene.
const TODAY_SIDE_PANEL_MAX_WIDTH = 720
// Matches the floating card, so docking keeps the panel's width.
const TODAY_SIDE_PANEL_DEFAULT_WIDTH = 340

export const SidePanel = memo(function SidePanel({ className }: { className?: string }): JSX.Element | null {
    const { theme } = useValues(themeLogic)
    const { enabledTabs, visibleTabs } = useValues(sidePanelLogic)
    const { selectedTab, sidePanelOpen } = useValues(sidePanelStateLogic)
    const { openSidePanel, closeSidePanel, setSidePanelAvailable } = useActions(sidePanelStateLogic)
    const { todayRailEnabled, phoneLayout } = useValues(todayShellLogic)
    const framed = todayRailEnabled && !phoneLayout

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
    const { setSidePanelWidth } = useActions(panelLayoutLogic)

    useEffect(() => {
        setSidePanelAvailable(true)
        return () => {
            setSidePanelAvailable(false)
        }
    }, [setSidePanelAvailable])

    // A tab is unavailable both when the scene will never offer it and while the scene is still
    // loading the object it describes. Staying open renders nothing until the tab resolves, which
    // keeps deep links like #panel=access-control working on a cold load. Leaving a scene is what
    // closes the panel, and sidePanelLogic handles that.
    const sidePanelOpenAndAvailable = selectedTab && sidePanelOpen && enabledTabs.includes(selectedTab)

    const { windowSize } = useWindowSize()

    const rawSidePanelWidth = !visibleTabs.length
        ? 0
        : sidePanelOpenAndAvailable
          ? Math.min(
                Math.max(
                    desiredSize ?? (framed ? TODAY_SIDE_PANEL_DEFAULT_WIDTH : DEFAULT_WIDTH),
                    SIDE_PANEL_MIN_WIDTH_COMPACT
                ),
                framed ? TODAY_SIDE_PANEL_MAX_WIDTH : Infinity
            )
          : 0

    const sidePanelWidth = windowSize.width != null ? Math.min(rawSidePanelWidth, windowSize.width) : rawSidePanelWidth

    // Update sidepanel width in panelLayoutLogic
    useEffect(() => {
        setSidePanelWidth(sidePanelWidth)
    }, [sidePanelWidth, setSidePanelWidth])

    if (!visibleTabs.length) {
        return null
    }

    if (framed) {
        return (
            <div
                className={cn(
                    '@container/side-panel relative flex h-full min-h-0 flex-col px-1 pb-1',
                    '[--side-panel-width:initial] [--scene-layout-rect-width:initial] [--scene-layout-rect-right:initial]',
                    isResizeInProgress && 'pointer-events-none',
                    !sidePanelOpenAndAvailable && 'hidden',
                    className
                )}
                ref={ref}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width: sidePanelOpenAndAvailable ? sidePanelWidth : '0px' }}
                id="side-panel"
            >
                {sidePanelOpenAndAvailable && (
                    <Resizer {...resizerLogicProps} visible={false} className="left-0 top-0 h-full" />
                )}
                {sidePanelOpenAndAvailable && activeTab && (
                    <TodayContextPanelCard docked tab={activeTab} className="h-full" />
                )}
            </div>
        )
    }

    return (
        <div
            className={cn(
                'SidePanel3000',
                sidePanelOpenAndAvailable && 'SidePanel3000--open justify-end',
                isResizeInProgress && 'SidePanel3000--resizing',
                '@container/side-panel bg-surface-secondary absolute top-0 right-0 bottom-0 h-full flex flex-col border-t-none',
                '[--side-panel-width:initial] [--scene-layout-rect-width:initial] [--scene-layout-rect-right:initial]',
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

            {PanelContent && <SidePanelContent activeTab={activeTab as SidePanelTab} Content={PanelContent} />}
        </div>
    )
})
