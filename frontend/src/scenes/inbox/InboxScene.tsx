import { useActions, useValues } from 'kea'

import { IconChevronRight, IconExpand } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonSkeleton, LemonTag, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { inboxSceneLogic } from './inboxSceneLogic'
import { SignalReport, SignalReportArtefact } from './types'

export const scene: SceneExport = {
    component: InboxScene,
    logic: inboxSceneLogic,
}

function ArtefactCard({ artefact }: { artefact: SignalReportArtefact }): JSX.Element {
    const content = artefact.content
    return (
        <div className="border rounded p-3 bg-surface-primary">
            <div className="flex items-center gap-2 mb-1">
                <LemonTag size="small">{artefact.type.replace('_', ' ')}</LemonTag>
                <TZLabel time={artefact.created_at} />
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

function ReportRow({ report }: { report: SignalReport }): JSX.Element {
    const { expandedReportId, artefacts, artefactsLoading } = useValues(inboxSceneLogic)
    const { setExpandedReportId, loadArtefacts } = useActions(inboxSceneLogic)

    const isExpanded = expandedReportId === report.id
    const reportArtefacts = artefacts[report.id]

    const handleToggle = (): void => {
        if (isExpanded) {
            setExpandedReportId(null)
        } else {
            setExpandedReportId(report.id)
            if (!artefacts[report.id]) {
                loadArtefacts({ reportId: report.id })
            }
        }
    }

    return (
        <div className="border rounded-lg bg-surface-primary overflow-hidden">
            <button
                type="button"
                className="w-full text-left px-4 py-3 flex items-start gap-3 hover:bg-surface-secondary transition-colors cursor-pointer bg-transparent border-none"
                onClick={handleToggle}
            >
                <div className="flex-shrink-0 mt-0.5">
                    <IconChevronRight
                        className={`size-4 text-tertiary transition-transform ${isExpanded ? 'rotate-90' : ''}`}
                    />
                </div>

                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                        <LemonTag size="small">Weight: {report.total_weight.toFixed(2)}</LemonTag>
                        <h3 className="text-sm font-semibold m-0 truncate flex-1">
                            {report.title || 'Untitled report'}
                        </h3>
                    </div>
                    {report.summary && <p className="text-sm text-secondary m-0 mt-1 line-clamp-2">{report.summary}</p>}
                </div>

                <div className="flex items-center gap-4 flex-shrink-0 text-xs text-tertiary">
                    {report.relevant_user_count !== null && report.relevant_user_count > 0 && (
                        <span title="Affected users">
                            {report.relevant_user_count} {report.relevant_user_count === 1 ? 'user' : 'users'}
                        </span>
                    )}
                    {report.signal_count > 0 && (
                        <span title="Number of signals">
                            {report.signal_count} {report.signal_count === 1 ? 'signal' : 'signals'}
                        </span>
                    )}
                    {report.artefact_count > 0 && (
                        <LemonBadge.Number count={report.artefact_count} maxDigits={3} size="small" />
                    )}
                    <TZLabel time={report.updated_at} />
                </div>
            </button>

            {isExpanded && (
                <div className="border-t px-4 py-3 bg-surface-secondary">
                    <div className="flex items-center justify-between mb-3">
                        <div className="text-xs text-tertiary space-x-4">
                            <span>
                                Weight: <strong>{report.total_weight.toFixed(2)}</strong>
                            </span>
                            <span>Created {humanFriendlyDetailedTime(report.created_at)}</span>
                        </div>
                    </div>

                    {report.summary && (
                        <div className="mb-3">
                            <p className="text-sm text-primary m-0">{report.summary}</p>
                        </div>
                    )}

                    <div>
                        <h4 className="text-xs font-semibold text-tertiary uppercase tracking-wide mb-2">Artefacts</h4>
                        {artefactsLoading && !reportArtefacts ? (
                            <div className="flex items-center gap-2 text-sm text-tertiary py-2">
                                <Spinner className="size-4" />
                                Loading artefacts...
                            </div>
                        ) : reportArtefacts && reportArtefacts.length > 0 ? (
                            <div className="space-y-2">
                                {reportArtefacts.map((artefact) => (
                                    <ArtefactCard key={artefact.id} artefact={artefact} />
                                ))}
                            </div>
                        ) : (
                            <p className="text-sm text-tertiary m-0">No artefacts yet.</p>
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}

function EmptyInbox(): JSX.Element {
    return (
        <div className="flex flex-col items-center justify-center py-16 text-center">
            <IconExpand className="size-12 text-tertiary mb-4" />
            <h3 className="text-lg font-semibold mb-1">Your inbox is empty</h3>
            <p className="text-sm text-secondary max-w-md">
                PostHog automatically analyzes user sessions and surfaces actionable reports here. Reports will appear
                as patterns are detected.
            </p>
        </div>
    )
}

function InboxSkeleton(): JSX.Element {
    return (
        <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="border rounded-lg px-4 py-3 bg-surface-primary">
                    <div className="flex items-center gap-3">
                        <LemonSkeleton className="w-4 h-4" />
                        <div className="flex-1">
                            <LemonSkeleton className="w-1/3 h-4 mb-2" />
                            <LemonSkeleton className="w-2/3 h-3" />
                        </div>
                        <LemonSkeleton className="w-16 h-3" />
                    </div>
                </div>
            ))}
        </div>
    )
}

export function InboxScene(): JSX.Element {
    const { reports, reportsLoading } = useValues(inboxSceneLogic)
    const { loadReports } = useActions(inboxSceneLogic)
    const isProductAutonomyEnabled = useFeatureFlag('PRODUCT_AUTONOMY')

    if (!isProductAutonomyEnabled) {
        return <></>
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Inbox"
                description="Actionable reports surfaced from automatic analysis of your product."
                resourceType={{ type: 'inbox' }}
                actions={
                    <LemonButton type="secondary" onClick={() => loadReports()} loading={reportsLoading} size="small">
                        Refresh
                    </LemonButton>
                }
            />

            {reportsLoading && reports.length === 0 ? (
                <InboxSkeleton />
            ) : reports.length === 0 ? (
                <EmptyInbox />
            ) : (
                <div className="space-y-2">
                    {reports.map((report) => (
                        <ReportRow key={report.id} report={report} />
                    ))}
                </div>
            )}
        </SceneContent>
    )
}

export default InboxScene
