import { useActions, useValues } from 'kea'
import { RefObject, useEffect, useRef } from 'react'

import { useWindowSize } from 'lib/hooks/useWindowSize'
import { ResizerLogicProps, resizerLogic } from 'lib/lemon-ui/Resizer/resizerLogic'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { SidePanelTab } from '~/types'

import { sidePanelLogic } from './sidePanelLogic'
import { sidePanelStateLogic } from './sidePanelStateLogic'

export const SIDE_PANEL_MIN_WIDTH_COMPACT = 330

export interface SidePanelFrameOptions {
    defaultWidth: number
    maxWidth?: number
    /** The most of the page the panel pushes aside. Past it the panel covers the page, which keeps its width. */
    pushMaxWidth?: number
}

export interface SidePanelFrame {
    ref: RefObject<HTMLDivElement>
    resizerLogicProps: ResizerLogicProps
    isResizeInProgress: boolean
    activeTab: SidePanelTab | null
    width: number
    /** The width the page gives up to the panel. Equal to `width` until the panel passes `pushMaxWidth`. */
    pushWidth: number
    hasTabs: boolean
}

/** The side panel's resizable frame: its open tab, width and resizer, shared by every layout that hosts it. */
export function useSidePanelFrame({
    defaultWidth,
    maxWidth = Infinity,
    pushMaxWidth = Infinity,
}: SidePanelFrameOptions): SidePanelFrame {
    const { enabledTabs, visibleTabs } = useValues(sidePanelLogic)
    const { selectedTab, sidePanelOpen } = useValues(sidePanelStateLogic)
    const { openSidePanel, closeSidePanel, setSidePanelAvailable } = useActions(sidePanelStateLogic)
    const { setSidePanelWidth } = useActions(panelLayoutLogic)
    const { windowSize } = useWindowSize()
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
    const activeTab = selectedTab && sidePanelOpen && enabledTabs.includes(selectedTab) ? selectedTab : null

    const rawWidth =
        visibleTabs.length && activeTab
            ? Math.min(Math.max(desiredSize ?? defaultWidth, SIDE_PANEL_MIN_WIDTH_COMPACT), maxWidth)
            : 0
    const width = windowSize.width != null ? Math.min(rawWidth, windowSize.width) : rawWidth

    const pushWidth = Math.min(width, pushMaxWidth)

    // Layouts and scenes read this as the room the panel takes from the page, so a covering panel reports only its push.
    useEffect(() => {
        setSidePanelWidth(pushWidth)
    }, [pushWidth, setSidePanelWidth])

    return {
        ref,
        resizerLogicProps,
        isResizeInProgress,
        activeTab,
        width,
        pushWidth,
        hasTabs: visibleTabs.length > 0,
    }
}
