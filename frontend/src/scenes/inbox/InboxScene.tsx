import { useActions, useValues } from 'kea'

import { IconArrowLeft, IconBug } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ScoutDetailView } from './components/config/scouts/ScoutDetailView'
import { ReportDetail, ReportDetailSkeleton } from './components/detail/ReportDetail'
import { FindingsPanel } from './components/findings/FindingsPanel'
import { InboxOnboardingBanner, InboxOnboardingTakeover } from './components/onboarding/InboxOnboarding'
import { ScratchpadPanel } from './components/scratchpad/ScratchpadPanel'
import { AgentSetupColumn } from './components/shell/AgentSetupColumn'
import { InboxScopeSelect } from './components/shell/InboxScopeSelect'
import { InboxTabBar } from './components/shell/InboxTabBar'
import { ArchivedTab } from './components/tabs/ArchivedTab'
import { NotActionableTab } from './components/tabs/NotActionableTab'
import { PullRequestsTab } from './components/tabs/PullRequestsTab'
import { ReportsTab } from './components/tabs/ReportsTab'
import { RunsTab } from './components/tabs/RunsTab'
import { inboxSceneLogic } from './inboxSceneLogic'
import { inboxOnboardingLogic } from './logics/inboxOnboardingLogic'
import { INBOX_TAB_DESCRIPTION, InboxTabKey, SignalReport, SignalRun } from './types'

export const scene: SceneExport = {
    component: InboxScene,
    logic: inboxSceneLogic,
}

/** Min scene-container width at which the setup rail fits beside the list. */
const SETUP_RAIL_MIN_PX = 1024

/** Tabs that show the centered report list (scope chrome in the header). Runs/Configuration are special. */
function isReportListTab(tab: InboxTabKey): boolean {
    return tab === 'pulls' || tab === 'reports' || tab === 'not-actionable' || tab === 'archived'
}

function ActiveTabBody({
    tab,
    signalRuns,
    signalRunsLoading,
}: {
    tab: InboxTabKey
    signalRuns: SignalRun[]
    signalRunsLoading: boolean
}): JSX.Element {
    switch (tab) {
        case 'pulls':
            return <PullRequestsTab />
        case 'reports':
            return <ReportsTab />
        case 'not-actionable':
            return <NotActionableTab />
        case 'archived':
            return <ArchivedTab />
        case 'runs':
            return <RunsTab runs={signalRuns} loading={signalRunsLoading} />
        case 'config':
            return <AgentSetupColumn layout="stacked" />
    }
}

/**
 * List view: a tab bar + scope select over the active tab's body, with the agent-setup
 * widgets to the right as a rail when the scene is wide enough (≥ ~72rem). Below that width
 * the rail is dropped and the widgets live in a Configuration tab instead. Each flat report
 * tab (Pull requests / Reports / Not actionable) owns its own filtered request, count,
 * search/filter chrome, and pagination via the keyed `reportListLogic`. Runs is project-wide
 * and chrome-less.
 */
function InboxListView(): JSX.Element {
    const { activeTab, signalRuns, signalRunsLoading } = useValues(inboxSceneLogic)
    const { onboardingMode } = useValues(inboxOnboardingLogic)
    const { ref: widthRef, size } = useResizeBreakpoints(
        { 0: 'narrow', [SETUP_RAIL_MIN_PX]: 'wide' },
        { initialSize: 'wide' }
    )
    const wide = size === 'wide'
    // Self-driving isn't set up and the inbox is empty: the inbox becomes a single locked "Welcome"
    // tab (the other tabs are visible but disabled) whose body is the onboarding card. The setup rail
    // is dropped too, so the onboarding is the whole story – just run the one command.
    const onboarding = onboardingMode === 'takeover'
    const showRail = wide && !onboarding
    // The rail and the Configuration tab are mutually exclusive – never leave 'config' active
    // (e.g. via a deep link) while the rail shows, or the rail and a config body would both appear.
    const effectiveTab = showRail && activeTab === 'config' ? 'pulls' : activeTab

    return (
        <div ref={widthRef} className="flex min-h-0 flex-1">
            <div className="flex flex-col min-h-0 flex-1 min-w-0">
                {/* pl-5 (20px) aligns the first tab label with the SceneTitleSection description above;
                    pr-6 matches the report list's px-6 so the scope select shares the list's right edge. */}
                <div className="flex items-end justify-between gap-2 border-b border-primary pl-5 pr-6 shrink-0">
                    <InboxTabBar showConfigTab={!wide} onboarding={onboarding} />
                    {!onboarding && isReportListTab(effectiveTab) && (
                        <div className="pb-1.5">
                            <InboxScopeSelect />
                        </div>
                    )}
                </div>
                <div className="flex-1 overflow-auto min-h-0">
                    {onboarding ? (
                        <InboxOnboardingTakeover />
                    ) : (
                        <ActiveTabBody
                            tab={effectiveTab}
                            signalRuns={signalRuns}
                            signalRunsLoading={signalRunsLoading}
                        />
                    )}
                </div>
            </div>
            {showRail && (
                <aside className="shrink-0 w-80 overflow-auto min-h-0 border-l border-primary">
                    <AgentSetupColumn layout="rail" />
                </aside>
            )}
        </div>
    )
}

/**
 * Detail view: replaces the list full-width. Report / PR / Not actionable render the unified
 * `ReportDetail`, which owns its own merged header (back link, title, copy link). The Runs tab no
 * longer opens an in-inbox detail — its rows link out to the standalone Tasks scene.
 */
function InboxDetailView({ report }: { report: SignalReport }): JSX.Element {
    const { activeTab } = useValues(inboxSceneLogic)

    return (
        <div className="flex flex-col min-h-0 flex-1 overflow-auto">
            <ReportDetail report={report} tab={activeTab} />
        </div>
    )
}

/**
 * Shared chrome for the full-width scout panels (scratchpad, findings): a "Scouts" back link over the
 * panel body, rendered full-width over the list like the scout detail. Reached from their callouts.
 */
function InboxPanelView({ onBack, children }: { onBack: () => void; children: JSX.Element }): JSX.Element {
    return (
        <div className="flex flex-col min-h-0 flex-1 overflow-auto">
            <div className="px-4 pt-3">
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconArrowLeft />}
                    onClick={onBack}
                    className="self-start"
                >
                    Scouts
                </LemonButton>
            </div>
            {children}
        </div>
    )
}

export function InboxScene(): JSX.Element {
    const {
        activeTab,
        isRunningSessionAnalysis,
        selectedReportId,
        selectedReport,
        selectedReportLoading,
        selectedScoutSkillName,
        isScratchpadOpen,
        isFindingsOpen,
    } = useValues(inboxSceneLogic)
    const { runSessionAnalysis, setScratchpadOpen, setFindingsOpen } = useActions(inboxSceneLogic)
    const { onboardingMode } = useValues(inboxOnboardingLogic)
    const { isDev } = useValues(preflightLogic)

    // Detail routes (report or scout) render full-width over the list (desktop parity), but the list view
    // stays *mounted* (just hidden) rather than being unmounted. That keeps `reportListLogic` and the scroll
    // container alive, so clicking "back" lands on the same scroll position with the same loaded pages —
    // instead of remounting and resetting to the first page at the top.
    const showDetail = !!selectedReportId || !!selectedScoutSkillName || isScratchpadOpen || isFindingsOpen

    return (
        <SceneContent className="gap-y-0 border-b-0 flex-1 min-h-0">
            <div className={showDetail ? 'hidden' : 'flex flex-col gap-y-4 flex-1 min-h-0'}>
                <SceneTitleSection
                    name="Inbox"
                    // The description explains the active tab so new users can orient themselves.
                    // In the onboarding takeover the tabs are locked, so keep the overall pitch.
                    description={
                        onboardingMode === 'takeover'
                            ? 'Self-driving for your product. Look through work done by PostHog agents – code changes and reports.'
                            : INBOX_TAB_DESCRIPTION[activeTab]
                    }
                    resourceType={{ type: 'inbox' }}
                    actions={
                        isDev ? (
                            <Tooltip title="Analyze the last 7 days of sessions">
                                <LemonButton
                                    type="secondary"
                                    onClick={() => runSessionAnalysis()}
                                    loading={isRunningSessionAnalysis}
                                    size="small"
                                    data-attr="run-session-analysis-button"
                                    tooltip="DEBUG-only"
                                    icon={<IconBug />}
                                >
                                    Run session analysis
                                </LemonButton>
                            </Tooltip>
                        ) : undefined
                    }
                />

                <div className="flex flex-col -mx-4 -mt-4 flex-1 min-h-0">
                    {/* The inbox always renders (its own list skeleton covers loading). When self-driving
                        isn't set up, the list view itself swaps in a locked "Welcome" onboarding tab; the
                        banner sits above the otherwise-normal inbox when there's already work to keep. */}
                    {onboardingMode === 'banner' && <InboxOnboardingBanner />}
                    <InboxListView />
                </div>
            </div>

            {showDetail && (
                <div className="flex flex-col -mx-4 flex-1 min-h-0">
                    {isFindingsOpen ? (
                        <InboxPanelView onBack={() => setFindingsOpen(false)}>
                            <FindingsPanel />
                        </InboxPanelView>
                    ) : isScratchpadOpen ? (
                        <InboxPanelView onBack={() => setScratchpadOpen(false)}>
                            <ScratchpadPanel />
                        </InboxPanelView>
                    ) : selectedScoutSkillName ? (
                        <ScoutDetailView skillName={selectedScoutSkillName} />
                    ) : selectedReport ? (
                        <InboxDetailView report={selectedReport} />
                    ) : selectedReportLoading ? (
                        <div className="flex flex-col min-h-0 flex-1 overflow-auto">
                            <ReportDetailSkeleton />
                        </div>
                    ) : (
                        <div className="flex flex-1 items-center justify-center text-sm text-tertiary">
                            Report not found.
                        </div>
                    )}
                </div>
            )}
        </SceneContent>
    )
}

export default InboxScene
