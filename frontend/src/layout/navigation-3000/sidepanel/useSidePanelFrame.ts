import { useActions, useValues } from 'kea'
import { RefObject, useEffect, useRef } from 'react'

import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { useWindowSize } from 'lib/hooks/useWindowSize'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { SidePanelTab } from '~/types'

import { sidePanelLogic } from './sidePanelLogic'
import { sidePanelStateLogic } from './sidePanelStateLogic'

export const SIDE_PANEL_MIN_WIDTH_COMPACT = 330

export interface SidePanelFrameOptions {
    defaultWidth: number
    maxWidth?: number
}

export interface SidePanelFrame {
    ref: RefObject<HTMLDivElement>
    resizerLogicProps: ResizerLogicProps
    isResizeInProgress: boolean
    activeTab: SidePanelTab | null
    width: number
    hasTabs: boolean
}

/** The side panel's resizable frame: its open tab, width and resizer, shared by every layout that hosts it. */
export function useSidePanelFrame({ defaultWidth, maxWidth = Infinity }: SidePanelFrameOptions): SidePanelFrame {
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

    useEffect(() => {
        setSidePanelWidth(width)
    }, [width, setSidePanelWidth])

    return { ref, resizerLogicProps, isResizeInProgress, activeTab, width, hasTabs: visibleTabs.length > 0 }
}
