import { useActions, useValues } from 'kea'
import { Suspense, useEffect, useState } from 'react'

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
import { TODAY_PANES } from './todayRailItems'
import { TodayRailTile } from './TodayRailTile'
import { TODAY_RAIL_WIDTH, TodayRailPane, railPaneHref, todayShellLogic } from './todayShellLogic'
import { TodaySpacesLogicMount } from './TodaySpacesLogicMount'
import { todayTourLogic } from './todayTourLogic'

// Flag-gated, so users without the flag skip the wizard chunk.
const WizardRailButton = lazyWithRetry(() =>
    import('products/wizard/frontend/views/run-sidebar/WizardRailButton').then(({ WizardRailButton }) => ({
        default: WizardRailButton,
    }))
)

const RAIL_PREVIEWS = Object.fromEntries(
    Object.keys(TODAY_PANES)
        .filter((pane) => pane !== 'home')
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
    const { activePane, effectivePhaiView, featureFlags, railPanes, sidebarVisible } = useValues(todayShellLogic)
    const { clickRailPane } = useActions(todayShellLogic)
    const { tourActive } = useValues(todayTourLogic)
    const [chatsPreviewed, setChatsPreviewed] = useState(false)
    const [pointerInRail, setPointerInRail] = useState(false)
    const [cardOpen, setCardOpen] = useState(false)
    useEffect(() => {
        if (!pointerInRail && !cardOpen) {
            setChatsPreviewed(false)
        }
    }, [pointerInRail, cardOpen])
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
                dataAttr={`today-rail-${pane}`}
                onPointerEnter={pane === 'spaces' ? () => setChatsPreviewed(true) : undefined}
            />
        )
        const preview = RAIL_PREVIEWS[pane]
        return preview ? (
            <TodayPreviewTrigger
                key={pane}
                payload={preview}
                disabled={activePane === pane && sidebarVisible}
                className="w-full min-w-0"
            >
                {tile}
            </TodayPreviewTrigger>
        ) : (
            tile
        )
    }

    return (
        <TodayPreviewCardProvider disabled={tourActive} onOpenChange={setCardOpen}>
            <nav
                aria-label="Main"
                onPointerEnter={() => setPointerInRail(true)}
                onPointerLeave={() => setPointerInRail(false)}
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
                <TodayMoreMenu overflowPanes={overflowPanes} renderTile={renderTile} />
                <TodayAccountMenu />
                {chatsPreviewed && <TodaySpacesLogicMount />}
            </nav>
        </TodayPreviewCardProvider>
    )
}
