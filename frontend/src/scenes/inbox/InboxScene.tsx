import { useActions, useValues } from 'kea'

import { IconArrowLeft, IconBug, IconExpand, IconGear, IconSearch } from '@posthog/icons'
import {
    LemonBadge,
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSkeleton,
    LemonTag,
    Link,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import ViewRecordingButton from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SourcesModal } from './InboxSetup'
import { inboxSceneLogic } from './inboxSceneLogic'
import { SignalReport, SignalReportArtefact } from './types'

export const scene: SceneExport = {
    component: InboxScene,
    logic: inboxSceneLogic,
}

function ReportListItem({ report }: { report: SignalReport }): JSX.Element {
    const { selectedReportId } = useValues(inboxSceneLogic)

    const isSelected = selectedReportId === report.id

    return (
        <Link
            to={urls.inbox(report.id)}
            className={`w-full text-left px-3 py-2.5 flex items-start gap-2 cursor-pointer rounded border border-primary ${
                isSelected ? 'bg-surface-primary' : 'bg-surface-secondary hover:bg-surface-tertiary'
            }`}
        >
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5 mb-0.5">
                    <h4 className="text-sm font-medium m-0 truncate flex-1">{report.title || 'Untitled report'}</h4>
                    <span className="text-xs text-tertiary whitespace-nowrap flex-shrink-0">
                        <TZLabel time={report.updated_at} />
                    </span>
                </div>
                {report.summary && <p className="text-xs text-secondary m-0 line-clamp-2">{report.summary}</p>}
                <div className="flex items-center gap-2 mt-1">
                    <LemonTag size="small">{report.total_weight.toFixed(1)}</LemonTag>
                    {report.relevant_user_count !== null && report.relevant_user_count > 0 && (
                        <span className="text-xs text-tertiary">
                            {report.relevant_user_count} {report.relevant_user_count === 1 ? 'user' : 'users'}
                        </span>
                    )}
                    {report.signal_count > 0 && (
                        <span className="text-xs text-tertiary">
                            {report.signal_count} {report.signal_count === 1 ? 'signal' : 'signals'}
                        </span>
                    )}
                    {report.artefact_count > 0 && (
                        <LemonBadge.Number count={report.artefact_count} maxDigits={3} size="small" />
                    )}
                </div>
            </div>
        </Link>
    )
}

function ReportListSkeleton(): JSX.Element {
    return (
        <div className="divide-y">
            {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="px-3 py-2.5">
                    <div className="flex items-center gap-2 mb-1">
                        <LemonSkeleton className="flex-1 h-4" />
                        <LemonSkeleton className="w-12 h-3" />
                    </div>
                    <LemonSkeleton className="w-4/5 h-3 mb-1" />
                    <LemonSkeleton className="w-16 h-4" />
                </div>
            ))}
        </div>
    )
}

function ReportListPane(): JSX.Element {
    const { filteredReports, reportsLoading, searchQuery, reports, selectedReportId } = useValues(inboxSceneLogic)
    const { setSearchQuery } = useActions(inboxSceneLogic)

    return (
        <div
            className={`flex-shrink-0 h-full p-3 overflow-y-auto w-full @[860px]/main-content-container:w-120 @[860px]/main-content-container:border-r border-primary ${
                selectedReportId != null ? 'hidden @[860px]/main-content-container:block' : ''
            }`}
        >
            <div className="pb-2">
                <LemonInput
                    type="search"
                    placeholder="Search reports..."
                    prefix={<IconSearch />}
                    className="bg-transparent"
                    value={searchQuery}
                    onChange={setSearchQuery}
                    size="small"
                    fullWidth
                />
            </div>
            <div className="flex flex-col gap-2">
                {reportsLoading && reports.length === 0 ? (
                    <ReportListSkeleton />
                ) : filteredReports.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-8 text-center px-4">
                        <p className="text-sm text-secondary m-0">
                            {searchQuery ? 'No reports match your search.' : 'No reports yet.'}
                        </p>
                    </div>
                ) : (
                    filteredReports.map((report: SignalReport) => <ReportListItem key={report.id} report={report} />)
                )}
            </div>
        </div>
    )
}

function ArtefactCard({ artefact }: { artefact: SignalReportArtefact }): JSX.Element {
    const content = artefact.content
    return (
        <div className="border rounded p-3 bg-surface-primary">
            <div className="flex items-center gap-2 mb-1">
                <LemonTag size="small">{artefact.type}</LemonTag>
                <TZLabel time={artefact.created_at} />
                {artefact.type === 'video_segment' && content.session_id && (
                    <ViewRecordingButton
                        sessionId={content.session_id}
                        timestamp={content.start_time}
                        size="xsmall"
                        type="secondary"
                        label="Play"
                    />
                )}
            </div>
            {content.session_id && (
                <p className="text-sm text-secondary m-0 mt-1 truncate">
                    Session: <span className="font-mono text-xs">{content.session_id}</span>
                </p>
            )}
            {content.summary && <p className="text-sm text-secondary m-0 mt-1">{content.summary}</p>}
        </div>
    )
}

function ReportDetailPane(): JSX.Element {
    const { selectedReport, artefacts, artefactsLoading } = useValues(inboxSceneLogic)

    const baseClasses = 'flex-1 min-w-0 h-full self-start bg-surface-primary overflow-y-auto flex flex-col'

    if (!selectedReport) {
        return (
            <div
                className={`${baseClasses} items-center justify-center text-center p-8 hidden @[860px]/main-content-container:flex`}
            >
                <IconExpand className="size-12 text-tertiary mb-4" />
                <h3 className="text-lg font-semibold mb-1">Welcome to Inbox</h3>
                <p className="text-sm text-secondary max-w-md mb-4">
                    PostHog automatically analyzes user sessions and surfaces actionable reports here. Select a report
                    from the list to view its details, including relevant artefacts like session recordings and
                    summaries.
                </p>
                <p className="text-xs text-tertiary max-w-sm">
                    Reports are generated as patterns are detected across your product's sessions. Configure signal
                    sources to customize what gets analyzed.
                </p>
            </div>
        )
    }

    const reportArtefacts = artefacts[selectedReport.id]

    return (
        <div className={baseClasses} style={{ height: 'calc(100vh - 11rem)' }}>
            <div className="flex-1 overflow-y-auto py-8 px-4 mx-auto max-w-240 max-w-[50%]">
                <Link
                    to={urls.inbox()}
                    className="inline-flex items-center gap-1 text-sm text-secondary mb-4 -mt-8 @[860px]/main-content-container:hidden"
                >
                    <IconArrowLeft className="size-4" />
                    All reports
                </Link>
                <div className="mb-4">
                    <div className="flex items-center gap-2 mb-1">
                        <h2 className="text-lg font-semibold m-0 flex-1">
                            {selectedReport.title || 'Untitled report'}
                        </h2>
                        <LemonTag size="small">Weight: {selectedReport.total_weight.toFixed(2)}</LemonTag>
                    </div>
                    {selectedReport.summary && (
                        <p className="text-sm text-secondary m-0 mt-2">{selectedReport.summary}</p>
                    )}
                    <div className="flex items-center gap-4 mt-2 text-xs text-tertiary">
                        {selectedReport.relevant_user_count !== null && selectedReport.relevant_user_count > 0 && (
                            <span>
                                {selectedReport.relevant_user_count}{' '}
                                {selectedReport.relevant_user_count === 1 ? 'user' : 'users'}
                            </span>
                        )}
                        {selectedReport.signal_count > 0 && (
                            <span>
                                {selectedReport.signal_count} {selectedReport.signal_count === 1 ? 'signal' : 'signals'}
                            </span>
                        )}
                        <span>Created {humanFriendlyDetailedTime(selectedReport.created_at)}</span>
                    </div>
                </div>

                <div>
                    <h4 className="text-xs font-semibold text-tertiary uppercase tracking-wide mb-2">Artefacts</h4>
                    {artefactsLoading && !reportArtefacts ? (
                        <div className="flex items-center gap-2 text-sm text-tertiary py-2">
                            <Spinner className="size-4" />
                            Loading artefacts...
                        </div>
                    ) : reportArtefacts && reportArtefacts.length > 0 ? (
                        <div className="space-y-2">
                            {reportArtefacts.map((artefact: SignalReportArtefact) => (
                                <ArtefactCard key={artefact.id} artefact={artefact} />
                            ))}
                        </div>
                    ) : (
                        <p className="text-sm text-tertiary m-0">No artefacts yet.</p>
                    )}
                </div>
            </div>
        </div>
    )
}

export function InboxScene(): JSX.Element {
    const { hasSessionAnalysisSource, isRunningSessionAnalysis } = useValues(inboxSceneLogic)
    const { runSessionAnalysis, openSourcesModal } = useActions(inboxSceneLogic)
    const { isDev } = useValues(preflightLogic)
    const isProductAutonomyEnabled = useFeatureFlag('PRODUCT_AUTONOMY')

    if (!isProductAutonomyEnabled) {
        return <></>
    }

    return (
        <SceneContent className="gap-y-0 border-b-0">
            <SourcesModal />
            <SceneTitleSection
                name="Inbox"
                description={null}
                resourceType={{ type: 'inbox' }}
                actions={
                    <div className="flex items-center gap-2">
                        {isDev && (
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
                        )}
                        <LemonButton type="secondary" icon={<IconGear />} size="small" onClick={openSourcesModal}>
                            Configure sources
                        </LemonButton>
                    </div>
                }
            />

            {!hasSessionAnalysisSource && (
                <LemonBanner type="info" action={{ children: 'Set up sources', onClick: openSourcesModal }}>
                    No signal sources are enabled. Set up sources to get new reports automatically.
                </LemonBanner>
            )}

            <div className="flex items-start -mx-4 h-[calc(100vh-6.375rem)]">
                <ReportListPane />
                <ReportDetailPane />
            </div>
        </SceneContent>
    )
}

export default InboxScene
