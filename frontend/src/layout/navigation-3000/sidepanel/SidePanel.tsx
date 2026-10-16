import './SidePanel.scss'

import { useActions, useValues } from 'kea'
import { memo, useEffect, useRef } from 'react'

import { IconApps, IconChat, IconLock, IconLogomark, IconNotebook, IconPulse } from '@posthog/icons'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { cn } from 'lib/utils/css-classes'
import { lazyWithRetry } from 'lib/utils/retryImport'

const NotebookPanel = lazyWithRetry(() =>
    import('scenes/notebooks/NotebookPanel/NotebookPanel').then((m) => ({ default: m.NotebookPanel }))
)
// The support panel renders the ticket editor, which pulls in tiptap extensions and lowlight.
const SidePanelSupport = lazyWithRetry(() =>
    import('./panels/support/SidePanelSupport').then((m) => ({ default: m.SidePanelSupport }))
)
// Discussion renders the comment composer, which pulls in the rich content editor and emoji picker.
const SidePanelDiscussion = lazyWithRetry(() =>
    import('./panels/discussion/SidePanelDiscussion').then((m) => ({ default: m.SidePanelDiscussion }))
)
const SidePanelAccessControl = lazyWithRetry(() =>
    import('./panels/access_control/SidePanelAccessControl').then((m) => ({ default: m.SidePanelAccessControl }))
)
const SidePanelAccessDetail = lazyWithRetry(() =>
    import('./panels/access_control/SidePanelAccessDetail').then((m) => ({ default: m.SidePanelAccessDetail }))
)
const SidePanelExports = lazyWithRetry(() =>
    import('./panels/exports/SidePanelExports').then((m) => ({ default: m.SidePanelExports }))
)
const CanvasSidePanel = lazyWithRetry(() =>
    import('products/canvas/frontend/sidePanel/CanvasSidePanel').then((m) => ({ default: m.CanvasSidePanel }))
)
const SidePanelActivity = lazyWithRetry(() =>
    import('./panels/activity/SidePanelActivity').then((m) => ({ default: m.SidePanelActivity }))
)

import { useWindowSize } from 'lib/hooks/useWindowSize'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { SidePanelTab } from '~/types'

import { SidePanelSupportIcon } from 'products/conversations/frontend/components/SidePanel/SidePanelSupportIcon'

import { SidePanelActivityIcon } from './panels/activity/SidePanelActivityIcon'
import { SidePanelDiscussionIcon } from './panels/discussion/SidePanelDiscussionIcon'
import { SidePanelExportsIcon } from './panels/exports/SidePanelExportsIcon'
import { SidePanelInfo, SidePanelInfoIcon } from './panels/info/SidePanelInfo'
import { SidePanelMax } from './panels/max/SidePanelMax'
import { SidePanelContent } from './SidePanelContent'
import { sidePanelLogic } from './sidePanelLogic'
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
    [SidePanelTab.AccessDetail]: {
        label: 'Access',
        Icon: IconLock,
        Content: SidePanelAccessDetail,
    },
    [SidePanelTab.Info]: {
        label: 'Actions',
        Icon: SidePanelInfoIcon,
        Content: SidePanelInfo,
    },
    [SidePanelTab.CanvasChat]: {
        label: 'Chat',
        Icon: IconChat,
        Content: CanvasSidePanel,
    },
    [SidePanelTab.CanvasBlocks]: {
        label: 'Blocks',
        Icon: IconApps,
        Content: CanvasSidePanel,
    },
    [SidePanelTab.CanvasTimeline]: {
        label: 'Timeline',
        Icon: IconPulse,
        Content: CanvasSidePanel,
    },
}

const DEFAULT_WIDTH = 512
const SIDE_PANEL_MIN_WIDTH_COMPACT = 330

export const SidePanel = memo(function SidePanel({ className }: { className?: string }): JSX.Element | null {
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
