import { useActions, useValues } from 'kea'

import { IconBug } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { AgentRunDetail } from './components/detail/AgentRunDetail'
import { InboxDetailHeader } from './components/detail/InboxDetailHeader'
import { ReportDetail, ReportDetailSkeleton } from './components/detail/ReportDetail'
import { AgentSetupColumn } from './components/shell/AgentSetupColumn'
import { InboxScopeSelect } from './components/shell/InboxScopeSelect'
import { InboxTabBar } from './components/shell/InboxTabBar'
import { NotActionableTab } from './components/tabs/NotActionableTab'
import { PullRequestsTab } from './components/tabs/PullRequestsTab'
import { ReportsTab } from './components/tabs/ReportsTab'
import { RunsTab } from './components/tabs/RunsTab'
import { inboxSceneLogic } from './inboxSceneLogic'
import { InboxTabKey, SignalReport } from './types'

export const scene: SceneExport = {
    component: InboxScene,
    logic: inboxSceneLogic,
}

/** Min scene-container width at which the setup rail fits beside the list. */
const SETUP_RAIL_MIN_PX = 1024

/** Tabs that show the centered report list (scope chrome in the header). Runs/Configuration are special. */
function isReportListTab(tab: InboxTabKey): boolean {
    return tab === 'pulls' || tab === 'reports' || tab === 'not-actionable'
}

function ActiveTabBody({ tab, runsReports }: { tab: InboxTabKey; runsReports: SignalReport[] }): JSX.Element {
    switch (tab) {
        case 'pulls':
            return <PullRequestsTab />
        case 'reports':
            return <ReportsTab />
        case 'not-actionable':
            return <NotActionableTab />
        case 'runs':
            return <RunsTab reports={runsReports} />
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
    const { activeTab, runsTabReports } = useValues(inboxSceneLogic)
    const { ref: widthRef, size } = useResizeBreakpoints(
        { 0: 'narrow', [SETUP_RAIL_MIN_PX]: 'wide' },
        { initialSize: 'wide' }
    )
    const showRail = size === 'wide'
    // The rail and the Configuration tab are mutually exclusive – never leave 'config' active
    // (e.g. via a deep link) while the rail shows, or the rail and a config body would both appear.
    const effectiveTab = showRail && activeTab === 'config' ? 'pulls' : activeTab

    return (
        <div ref={widthRef} className="flex min-h-0 flex-1">
            <div className="flex flex-col min-h-0 flex-1 min-w-0">
                {/* pl-5 (20px) aligns the first tab label with the SceneTitleSection description above. */}
                <div className="flex items-end justify-between gap-2 border-b border-primary pl-5 pr-2 shrink-0">
                    <InboxTabBar showConfigTab={!showRail} />
                    {isReportListTab(effectiveTab) && (
                        <div className="pb-1.5">
                            <InboxScopeSelect />
                        </div>
                    )}
                </div>
                <div className="flex-1 overflow-auto min-h-0">
                    <ActiveTabBody tab={effectiveTab} runsReports={runsTabReports} />
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
 * `ReportDetail`, which owns its own merged header (back link, title, copy link). The Runs view
 * keeps `AgentRunDetail` under the shared `InboxDetailHeader`.
 */
function InboxDetailView({ report }: { report: SignalReport }): JSX.Element {
    const { activeTab } = useValues(inboxSceneLogic)

    if (activeTab === 'runs') {
        return (
            <div className="flex flex-col min-h-0 flex-1 overflow-auto">
                <InboxDetailHeader report={report} tab={activeTab} />
                <AgentRunDetail report={report} />
            </div>
        )
    }

    return (
        <div className="flex flex-col min-h-0 flex-1 overflow-auto">
            <ReportDetail report={report} tab={activeTab} />
        </div>
    )
}

export function InboxScene(): JSX.Element {
    const { isRunningSessionAnalysis, selectedReportId, selectedReport, selectedReportLoading } =
        useValues(inboxSceneLogic)
    const { runSessionAnalysis } = useActions(inboxSceneLogic)
    const { isDev } = useValues(preflightLogic)

    // Detail route: render the report full-width, replacing the list (desktop parity).
    if (selectedReportId) {
        return (
            <SceneContent className="gap-y-0 border-b-0 flex-1 min-h-0">
                <div className="flex flex-col -mx-4 flex-1 min-h-0">
                    {selectedReport ? (
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
            </SceneContent>
        )
    }

    return (
        <SceneContent className="gap-y-2 border-b-0 flex-1 min-h-0">
            <SceneTitleSection
                name="Inbox"
                description="Work done by your agents – pull requests, reports, and live runs."
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

            <div className="flex flex-col -mx-4 flex-1 min-h-0">
                <InboxListView />
            </div>
        </SceneContent>
    )
}

export default InboxScene
