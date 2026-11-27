import { useActions, useValues } from 'kea'
import { Suspense, useEffect, useRef, useState } from 'react'

import { cn } from '@posthog/quill'
import { PostHogErrorBoundary } from '@posthog/react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { projectLogic } from 'scenes/projectLogic'

import { TodayAccountMenu } from './TodayAccountMenu'
import { TodayMoreMenu } from './TodayMoreMenu'
import { TodayPreviewCardProvider } from './TodayPreviewCardProvider'
import type { TodayRailPreview } from './todayPreviewCards'
import { TodayPreviewTrigger } from './TodayPreviewTrigger'
import { TODAY_PANES } from './todayRailItems'
import { TODAY_RAIL_FOOT_PANE } from './todayRailLayout'
import { todayRailLayoutLogic } from './todayRailLayoutLogic'
import {
    TODAY_RAIL_SHORT_PADDING_CLASS,
    TODAY_RAIL_SHORT_STACK_CLASS,
    TodayRailMetrics,
    todayRailMetrics,
} from './todayRailShort'
import { TodayRailTile } from './TodayRailTile'
import { TODAY_RAIL_WIDTH, TodayRailPane, railPaneHref, todayShellLogic } from './todayShellLogic'
import { TodaySpacesLogicMount } from './TodaySpacesLogicMount'
import { todayTourLogic } from './todayTourLogic'
import { useTodayRailFlip } from './useTodayRailFlip'

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

export function railPanesThatFit(
    panes: TodayRailPane[],
    height: number | undefined,
    { tileHeight, gap }: TodayRailMetrics
): number {
    if (height === undefined) {
        return panes.length
    }
    return Math.max(0, Math.floor((height + gap) / (tileHeight + gap)))
}

export function TodayRail(): JSX.Element {
    const { activePane, effectivePhaiView, featureFlags, sidebarVisible } = useValues(todayShellLogic)
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
    const paneListRef = useRef<HTMLDivElement>(null)
    const { height: paneListHeight } = useResizeObserver<HTMLDivElement>({ ref: paneListRef })
    const { windowSize } = useWindowSize()
    const { shownRailPanes: listPanes, footPaneShown, customizeOpen } = useValues(todayRailLayoutLogic)
    const fitCount = railPanesThatFit(listPanes, paneListHeight, todayRailMetrics(windowSize.height))
    const visiblePanes = listPanes.slice(0, fitCount)
    const overflowPanes = listPanes.slice(fitCount)
    // Only while the person arranges the rail: a pane that moves into More on a short window just goes.
    useTodayRailFlip(paneListRef, visiblePanes, customizeOpen)

    const renderTile = (pane: TodayRailPane): JSX.Element => {
        const tile = (
            <TodayRailTile
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
                className={cn(
                    'TodayShell__rail flex shrink-0 flex-col items-center gap-3 bg-[var(--chrome)] pt-3 pb-3',
                    TODAY_RAIL_SHORT_STACK_CLASS,
                    TODAY_RAIL_SHORT_PADDING_CLASS
                )}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width: TODAY_RAIL_WIDTH }}
            >
                <div
                    ref={paneListRef}
                    className={cn(
                        'flex min-h-0 w-full flex-1 flex-col items-center gap-3 overflow-hidden',
                        TODAY_RAIL_SHORT_STACK_CLASS
                    )}
                >
                    {visiblePanes.map((pane) => (
                        <div key={pane} data-flip-key={pane} className="flex w-full justify-center">
                            {renderTile(pane)}
                        </div>
                    ))}
                </div>
                {footPaneShown && renderTile(TODAY_RAIL_FOOT_PANE)}
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
                <TodayMoreMenu overflowPanes={overflowPanes} />
                <TodayAccountMenu />
                {chatsPreviewed && <TodaySpacesLogicMount />}
            </nav>
        </TodayPreviewCardProvider>
    )
}
