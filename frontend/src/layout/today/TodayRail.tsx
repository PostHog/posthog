import { useActions, useValues } from 'kea'
import { Suspense } from 'react'

import { PostHogErrorBoundary } from '@posthog/react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { projectLogic } from 'scenes/projectLogic'

import { TodayAccountMenu } from './TodayAccountMenu'
import { TodayMoreMenu } from './TodayMoreMenu'
import { TODAY_PANES, TODAY_RAIL_FOOTER_PANES } from './todayRailItems'
import { TodayRailTile } from './TodayRailTile'
import { TODAY_RAIL_WIDTH, TodayRailPane, railPaneHref, todayShellLogic } from './todayShellLogic'

// Flag-gated, so users without the flag skip the wizard chunk.
const WizardRailButton = lazyWithRetry(() =>
    import('products/wizard/frontend/views/run-sidebar/WizardRailButton').then(({ WizardRailButton }) => ({
        default: WizardRailButton,
    }))
)

// pinned: autocapture data-attr. The Settings tile kept the attribute of the gear button it replaced.
const RAIL_DATA_ATTRS: Partial<Record<TodayRailPane, string>> = { settings: 'today-settings' }

export function TodayRail(): JSX.Element {
    const { activePane, effectivePhaiView, featureFlags, railPanes } = useValues(todayShellLogic)
    const { clickRailPane } = useActions(todayShellLogic)
    const wizardUiEnabled = useFeatureFlag('WIZARD_UI_ENABLED')
    const { currentProjectId } = useValues(projectLogic)

    const renderTile = (pane: TodayRailPane): JSX.Element => (
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

    return (
        <nav
            aria-label="Main"
            className="TodayShell__rail flex shrink-0 flex-col items-center gap-3 bg-[var(--chrome)] pt-3 pb-3"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: TODAY_RAIL_WIDTH }}
        >
            {railPanes.map(renderTile)}
            {wizardUiEnabled &&
                currentProjectId !== null && (
                    // A local boundary keeps a failed wizard chunk from reaching the shell's
                    // ChunkLoadErrorBoundary, which reloads the whole app.
                    <PostHogErrorBoundary fallback={<></>}>
                        <Suspense fallback={null}>
                            <WizardRailButton projectId={String(currentProjectId)} />
                        </Suspense>
                    </PostHogErrorBoundary>
                )}
            <div className="mt-auto flex w-full flex-col items-center gap-3">
                <TodayMoreMenu />
                {TODAY_RAIL_FOOTER_PANES.map(renderTile)}
            </div>
            <TodayAccountMenu />
        </nav>
    )
}
