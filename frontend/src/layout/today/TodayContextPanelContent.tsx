import { useValues } from 'kea'
import { Suspense, useState } from 'react'

import { Spinner } from '@posthog/quill'

import { lazyWithRetry } from 'lib/utils/retryImport'
import { ChunkLoadErrorBoundary } from 'scenes/ChunkLoadErrorBoundary'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { SIDE_PANEL_TABS } from '~/layout/navigation-3000/sidepanel/sidePanelTabs'
import { SidePanelTab } from '~/types'

import { TodayAiPanel } from './TodayAiPanel'
import { todayContextPanelLogic } from './todayContextPanelLogic'

// The support panel renders the ticket editor, which pulls in tiptap extensions and lowlight.
const TodaySupportPanel = lazyWithRetry(() =>
    import('./TodaySupportPanel').then((m) => ({ default: m.TodaySupportPanel }))
)

const QuillAccessControlPanel = lazyWithRetry(() =>
    import('~/layout/navigation-3000/sidepanel/panels/access_control/quill/QuillAccessControlPanel').then((m) => ({
        default: m.QuillAccessControlPanel,
    }))
)

const QuillActivityPanel = lazyWithRetry(() =>
    import('~/layout/navigation-3000/sidepanel/panels/activity/quill/QuillActivityPanel').then((m) => ({
        default: m.QuillActivityPanel,
    }))
)

type SwitchDirection = 'forward' | 'backward'

export function TodayContextPanelContent({ tab }: { tab: SidePanelTab }): JSX.Element {
    const { panelTabs } = useValues(todayContextPanelLogic)
    const [shownTab, setShownTab] = useState(tab)
    const [direction, setDirection] = useState<SwitchDirection | null>(null)

    // Adjusting state during render, so the panel mounts with its direction already set and never flashes still.
    if (shownTab !== tab) {
        setDirection(panelTabs.indexOf(tab) >= panelTabs.indexOf(shownTab) ? 'forward' : 'backward')
        setShownTab(tab)
    }

    const Content = SIDE_PANEL_TABS[tab].Content

    return (
        <div key={tab} data-direction={direction ?? undefined} className="TodayContextPanelContent">
            <ErrorBoundary>
                {/* Keep chunk-load failures out of the panel error reporter so stale assets reload once instead. */}
                <ChunkLoadErrorBoundary>
                    <Suspense fallback={<Spinner className="mx-auto mt-16" />}>
                        {/* PostHog AI, Support, Access control and Activity are rebuilt in quill for the card. The other tabs keep their panels. */}
                        {tab === SidePanelTab.Max ? (
                            <TodayAiPanel />
                        ) : tab === SidePanelTab.Support ? (
                            <TodaySupportPanel />
                        ) : tab === SidePanelTab.Activity ? (
                            <QuillActivityPanel />
                        ) : tab === SidePanelTab.AccessControl ? (
                            <QuillAccessControlPanel />
                        ) : (
                            <Content />
                        )}
                    </Suspense>
                </ChunkLoadErrorBoundary>
            </ErrorBoundary>
        </div>
    )
}
