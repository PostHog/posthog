import { useActions, useValues } from 'kea'
import { Suspense } from 'react'

import { PostHogErrorBoundary } from '@posthog/react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { projectLogic } from 'scenes/projectLogic'

import { TodayAccountMenu } from './TodayAccountMenu'
import { TodayMoreMenu } from './TodayMoreMenu'
import { TodayPreviewCardProvider } from './TodayPreviewCardProvider'
import type { TodayRailPreview } from './todayPreviewCards'
import { TodayPreviewTrigger } from './TodayPreviewTrigger'
import { TODAY_PANES, TODAY_RAIL_FOOTER_PANES } from './todayRailItems'
import { TodayRailTile } from './TodayRailTile'
import { TODAY_RAIL_WIDTH, TodayRailPane, railPaneHref, todayShellLogic } from './todayShellLogic'
import { todayTourLogic } from './todayTourLogic'

// Flag-gated, so users without the flag skip the wizard chunk.
const WizardRailButton = lazyWithRetry(() =>
    import('products/wizard/frontend/views/run-sidebar/WizardRailButton').then(({ WizardRailButton }) => ({
        default: WizardRailButton,
    }))
)

// pinned: autocapture data-attr. The Settings tile kept the attribute of the gear button it replaced.
const RAIL_DATA_ATTRS: Partial<Record<TodayRailPane, string>> = { settings: 'today-settings' }

const RAIL_PREVIEWS = Object.fromEntries(
    Object.keys(TODAY_PANES)
        .filter((pane) => pane !== 'home' && pane !== 'settings')
        .map((pane) => [pane, { kind: 'rail', pane }])
) as Partial<Record<TodayRailPane, TodayRailPreview>>

const RAIL_TILE_HEIGHT = 56
const RAIL_GAP = 12

export function railPanesThatFit(panes: TodayRailPane[], height: number | undefined): number {
    if (height === undefined) {
        return panes.length
    }
    return Math.max(0, Math.floor((height + RAIL_GAP) / (RAIL_TILE_HEIGHT + RAIL_GAP)))
}

export function TodayRail(): JSX.Element {
    const { activePane, effectivePhaiView, featureFlags, railPanes } = useValues(todayShellLogic)
    const { clickRailPane } = useActions(todayShellLogic)
    const { tourActive } = useValues(todayTourLogic)
    const wizardUiEnabled = useFeatureFlag('WIZARD_UI_ENABLED')
    const { currentProjectId } = useValues(projectLogic)
    const { ref: paneListRef, height: paneListHeight } = useResizeObserver<HTMLDivElement>()
    const fitCount = railPanesThatFit(railPanes, paneListHeight)
    const visiblePanes = railPanes.slice(0, fitCount)
    const overflowPanes = railPanes.slice(fitCount)

    const renderTile = (pane: TodayRailPane): JSX.Element => {
        const tile = (
            <TodayRailTile
                key={pane}
                label={TODAY_PANES[pane].label}
                icon={TODAY_PANES[pane].icon}
                active={activePane === pane}
                to={railPaneHref(pane, effectivePhaiView, featureFlags)}
                onClick={() => clickRailPane(pane)}
                dataAttr={RAIL_DATA_ATTRS[pane] ?? `today-rail-${pane}`}
            />
        )
        const preview = RAIL_PREVIEWS[pane]
        return preview ? (
            <TodayPreviewTrigger key={pane} payload={preview} disabled={activePane === pane} className="w-full min-w-0">
                {tile}
            </TodayPreviewTrigger>
        ) : (
            tile
        )
    }

    return (
        <TodayPreviewCardProvider disabled={tourActive}>
            <nav
                aria-label="Main"
                className="TodayShell__rail flex shrink-0 flex-col items-center gap-3 bg-[var(--chrome)] pt-3 pb-3"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width: TODAY_RAIL_WIDTH }}
            >
                <div
                    ref={paneListRef}
                    className="flex min-h-0 w-full flex-1 flex-col items-center gap-3 overflow-hidden"
                >
                    {visiblePanes.map(renderTile)}
                </div>
                {wizardUiEnabled &&
                    currentProjectId !== null && (
                        // A local boundary keeps a failed wizard chunk from reaching the shell's
                        // ChunkLoadErrorBoundary, which reloads the whole app.
                        <PostHogErrorBoundary fallback={<></>}>
                            <Suspense fallback={null}>
                                <WizardRailButton key={currentProjectId} projectId={String(currentProjectId)} />
                            </Suspense>
                        </PostHogErrorBoundary>
                    )}
                <div className="flex w-full flex-col items-center gap-3">
                    <TodayMoreMenu overflowPanes={overflowPanes} />
                    {TODAY_RAIL_FOOTER_PANES.map(renderTile)}
                </div>
                <TodayAccountMenu />
            </nav>
        </TodayPreviewCardProvider>
    )
}
