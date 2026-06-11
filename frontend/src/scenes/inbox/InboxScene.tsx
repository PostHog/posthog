import { useActions, useValues } from 'kea'

import { IconArrowLeft, IconBug } from '@posthog/icons'
import { LemonButton, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ConventionalCommitScopeTag } from './components/cards/ReportCard'
import { AgentsTab } from './components/config/AgentsTab'
import { AgentRunDetail } from './components/detail/AgentRunDetail'
import { PullRequestDetail } from './components/detail/PullRequestDetail'
import { ReportDetail } from './components/detail/ReportDetail'
import { InboxBulkSelectionBar } from './components/shell/InboxBulkSelectionBar'
import { InboxScopeSelect } from './components/shell/InboxScopeSelect'
import { InboxSearchFilterBar } from './components/shell/InboxSearchFilterBar'
import { InboxTabBar } from './components/shell/InboxTabBar'
import { PullRequestsTab } from './components/tabs/PullRequestsTab'
import { ReportsTab } from './components/tabs/ReportsTab'
import { RunsTab } from './components/tabs/RunsTab'
import { inboxSceneLogic } from './inboxSceneLogic'
import { INBOX_TAB_LABEL, InboxTabKey, SignalReport } from './types'
import { displayConventionalCommitTitle, parseConventionalCommitTitle } from './utils/reportPresentation'

export const scene: SceneExport = {
    component: InboxScene,
    logic: inboxSceneLogic,
}

/** Tabs that show the centered report list (search + scope chrome). Runs and Agents are special. */
function isReportListTab(tab: InboxTabKey): boolean {
    return tab === 'pulls' || tab === 'reports'
}

function ActiveTabBody({ tab, reports }: { tab: InboxTabKey; reports: SignalReport[] }): JSX.Element {
    if (tab === 'agents') {
        return <AgentsTab />
    }
    if (tab === 'pulls') {
        return <PullRequestsTab reports={reports} />
    }
    if (tab === 'runs') {
        return <RunsTab reports={reports} />
    }
    return <ReportsTab reports={reports} />
}

function SelectedReportDetail({ tab, report }: { tab: InboxTabKey; report: SignalReport }): JSX.Element {
    if (tab === 'pulls') {
        return <PullRequestDetail report={report} />
    }
    if (tab === 'runs') {
        return <AgentRunDetail report={report} />
    }
    return <ReportDetail report={report} />
}

/**
 * List view: full-width tab bar + scope select, then a centered max-w-4xl column
 * with the search/filter bar, bulk-selection bar, and the active tab's card list.
 * Mirrors desktop `InboxView` (header) + `InboxReportListTab` (centered body).
 * The Runs tab is intentionally chrome-less (no search / scope).
 */
function InboxListView(): JSX.Element {
    const { activeTab, visibleReports, reportsLoading, tabCounts } = useValues(inboxSceneLogic)
    const { loadReports } = useActions(inboxSceneLogic)

    return (
        <div className="flex flex-col min-h-0 flex-1">
            <div className="flex items-end justify-between gap-2 border-b border-primary px-2 shrink-0">
                <InboxTabBar counts={tabCounts} />
                {isReportListTab(activeTab) && (
                    <div className="pb-1.5">
                        <InboxScopeSelect />
                    </div>
                )}
            </div>
            <div className="flex-1 overflow-auto min-h-0">
                {isReportListTab(activeTab) && (
                    <div className="mx-auto max-w-4xl px-6 pt-4 flex flex-col gap-4">
                        <InboxSearchFilterBar onRefresh={() => loadReports()} refreshing={reportsLoading} />
                        <InboxBulkSelectionBar />
                    </div>
                )}
                <ActiveTabBody tab={activeTab} reports={visibleReports} />
            </div>
        </div>
    )
}

/**
 * Detail view: replaces the list full-width (no tab bar / search). A back link
 * returns to the active tab's list; the title row mirrors desktop
 * `InboxDetailPageHeader`. The detail body owns its badges / actions / sections.
 */
function InboxDetailView({ report }: { report: SignalReport }): JSX.Element {
    const { activeTab } = useValues(inboxSceneLogic)
    const conventionalTitle = parseConventionalCommitTitle(report.title)
    const displayTitle = displayConventionalCommitTitle(report.title, 'Untitled report')

    return (
        <div className="flex flex-col min-h-0 flex-1 overflow-auto">
            <div className="shrink-0 border-b border-primary px-6 pt-5 pb-4 flex flex-col gap-3">
                <Link
                    to={urls.inbox(activeTab)}
                    className="inline-flex w-fit items-center gap-1.5 text-[12.5px] text-secondary hover:text-default no-underline"
                >
                    <IconArrowLeft className="text-sm" />
                    {INBOX_TAB_LABEL[activeTab]}
                </Link>
                <div className="flex items-center gap-2 flex-wrap min-w-0">
                    {conventionalTitle && (
                        <ConventionalCommitScopeTag type={conventionalTitle.type} scope={conventionalTitle.scope} />
                    )}
                    <h1 className="min-w-0 m-0 text-2xl font-bold leading-tight tracking-tight">{displayTitle}</h1>
                </div>
            </div>
            <SelectedReportDetail tab={activeTab} report={report} />
        </div>
    )
}

export function InboxScene(): JSX.Element {
    const { isRunningSessionAnalysis, selectedReportId, selectedReport, reportsLoading } = useValues(inboxSceneLogic)
    const { runSessionAnalysis } = useActions(inboxSceneLogic)
    const { isDev } = useValues(preflightLogic)

    // Detail route: render the report full-width, replacing the list (desktop parity).
    if (selectedReportId) {
        return (
            <SceneContent className="gap-y-0 border-b-0">
                <div className="flex flex-col -mx-4 h-[calc(100vh-3.5rem)]">
                    {selectedReport ? (
                        <InboxDetailView report={selectedReport} />
                    ) : (
                        <div className="flex flex-1 items-center justify-center gap-2 text-sm text-tertiary">
                            <Spinner className="size-4" />
                            {reportsLoading ? 'Loading report…' : 'Report not found.'}
                        </div>
                    )}
                </div>
            </SceneContent>
        )
    }

    return (
        <SceneContent className="gap-y-2 border-b-0">
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

            <div className="flex flex-col -mx-4 h-[calc(100vh-9.5rem)]">
                <InboxListView />
            </div>
        </SceneContent>
    )
}

export default InboxScene
