import { useValues } from 'kea'
import { ComponentType, Suspense, memo, useState } from 'react'

import { Spinner } from '@posthog/quill'

import { lazyWithRetry } from 'lib/utils/retryImport'
import { ChunkLoadErrorBoundary } from 'scenes/ChunkLoadErrorBoundary'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { SIDE_PANEL_TABS } from '~/layout/navigation-3000/sidepanel/sidePanelTabs'
import { SidePanelTab } from '~/types'

import { TodayAiPanel } from './TodayAiPanel'
import { todayContextPanelLogic } from './todayContextPanelLogic'

// The quill rebuilds of the side panel tabs. Every other tab keeps its own panel. Support is lazy because the ticket
// editor pulls in tiptap extensions and lowlight.
const QUILL_TAB_PANELS: Partial<Record<SidePanelTab, ComponentType>> = {
    [SidePanelTab.Max]: TodayAiPanel,
    [SidePanelTab.Support]: lazyWithRetry(() =>
        import('./TodaySupportPanel').then((m) => ({ default: m.TodaySupportPanel }))
    ),
    [SidePanelTab.Activity]: lazyWithRetry(() =>
        import('~/layout/navigation-3000/sidepanel/panels/activity/quill/QuillActivityPanel').then((m) => ({
            default: m.QuillActivityPanel,
        }))
    ),
    [SidePanelTab.AccessControl]: lazyWithRetry(() =>
        import('~/layout/navigation-3000/sidepanel/panels/access_control/quill/QuillAccessControlPanel').then((m) => ({
            default: m.QuillAccessControlPanel,
        }))
    ),
}

type SwitchDirection = 'forward' | 'backward'

// Memoized, so resizing or dragging the panel doesn't rerender the open tab's content on every frame.
export const TodayContextPanelContent = memo(function TodayContextPanelContent({
    tab,
}: {
    tab: SidePanelTab
}): JSX.Element {
    const { panelTabs } = useValues(todayContextPanelLogic)
    const [shownTab, setShownTab] = useState(tab)
    const [direction, setDirection] = useState<SwitchDirection | null>(null)

    // Adjusting state during render, so the panel mounts with its direction already set and never flashes still.
    if (shownTab !== tab) {
        setDirection(panelTabs.indexOf(tab) >= panelTabs.indexOf(shownTab) ? 'forward' : 'backward')
        setShownTab(tab)
    }

    const Content = QUILL_TAB_PANELS[tab] ?? SIDE_PANEL_TABS[tab].Content

    return (
        <div key={tab} data-direction={direction ?? undefined} className="TodayContextPanelContent">
            <ErrorBoundary>
                {/* Keep chunk-load failures out of the panel error reporter so stale assets reload once instead. */}
                <ChunkLoadErrorBoundary>
                    <Suspense fallback={<Spinner className="mx-auto mt-16" />}>
                        <Content />
                    </Suspense>
                </ChunkLoadErrorBoundary>
            </ErrorBoundary>
        </div>
    )
})
