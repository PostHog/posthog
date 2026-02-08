import { useActions, useValues } from 'kea'

import { IconChevronRight, IconExpand } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonCollapse, LemonSkeleton, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { inboxSceneLogic } from './inboxSceneLogic'
import {
    SignalReport,
    SignalReportArtefact,
    SignalReportDebugResponse,
    SignalReportDebugSegment,
    SignalReportDebugSession,
    SignalReportPipelineMetadata,
} from './types'

export const scene: SceneExport = {
    component: InboxScene,
    logic: inboxSceneLogic,
}

function priorityLabel(weight: number): { text: string; status: 'danger' | 'warning' | 'default' } {
    if (weight >= 0.8) {
        return { text: 'Critical', status: 'danger' }
    }
    if (weight >= 0.5) {
        return { text: 'Important', status: 'warning' }
    }
    return { text: 'Info', status: 'default' }
}

function relativeTime(dateStr: string): string {
    const date = dayjs(dateStr)
    const now = dayjs()
    const diffMinutes = now.diff(date, 'minute')

    if (diffMinutes < 1) {
        return 'Just now'
    }
    if (diffMinutes < 60) {
        return `${diffMinutes}m ago`
    }
    const diffHours = now.diff(date, 'hour')
    if (diffHours < 24) {
        return `${diffHours}h ago`
    }
    const diffDays = now.diff(date, 'day')
    if (diffDays < 7) {
        return `${diffDays}d ago`
    }
    return humanFriendlyDetailedTime(dateStr, 'MMM D', 'h:mm A')
}

function distanceColor(distance: number | null): string {
    if (distance === null) {
        return 'text-tertiary'
    }
    if (distance < 0.2) {
        return 'text-success'
    }
    if (distance < 0.35) {
        return 'text-warning'
    }
    return 'text-danger'
}

function PipelinePanel({ metadata }: { metadata: SignalReportPipelineMetadata }): JSX.Element {
    const totalWeight = metadata.labeling ? Math.log(1 + metadata.labeling.relevant_user_count).toFixed(2) : null

    return (
        <div className="space-y-2 text-sm">
            <div className="flex items-center gap-2">
                <span className="text-tertiary">Algorithm:</span>
                <LemonTag size="small">
                    {metadata.algorithm === 'agglomerative'
                        ? 'Agglomerative'
                        : metadata.algorithm === 'iterative_kmeans'
                          ? 'Iterative K-means'
                          : metadata.algorithm}
                </LemonTag>
            </div>
            <div className="flex items-center gap-2">
                <span className="text-tertiary">Cluster size:</span>
                <span>{metadata.cluster_size}</span>
            </div>
            {metadata.intra_cluster_distance_p95 !== null && (
                <div className="flex items-center gap-2">
                    <span className="text-tertiary">Intra-cluster distance (p95):</span>
                    <span className={distanceColor(metadata.intra_cluster_distance_p95)}>
                        {metadata.intra_cluster_distance_p95.toFixed(4)}
                    </span>
                </div>
            )}
            <div className="flex items-center gap-2">
                <span className="text-tertiary">Cluster type:</span>
                {metadata.is_new_cluster ? (
                    <LemonTag type="highlight" size="small">
                        New
                    </LemonTag>
                ) : (
                    <LemonTag type="default" size="small">
                        Matched
                    </LemonTag>
                )}
            </div>
            {!metadata.is_new_cluster && metadata.matched_report_id && (
                <div className="flex items-center gap-2">
                    <span className="text-tertiary">Matched report:</span>
                    <span className="font-mono text-xs">{metadata.matched_report_id}</span>
                    {metadata.match_distance !== null && (
                        <span className={`${distanceColor(metadata.match_distance)}`}>
                            (distance: {metadata.match_distance.toFixed(4)})
                        </span>
                    )}
                </div>
            )}
            {totalWeight && (
                <div className="flex items-center gap-2">
                    <span className="text-tertiary">Weight calculation:</span>
                    <span className="font-mono text-xs">
                        log(1 + {metadata.labeling?.relevant_user_count}) = {totalWeight}
                    </span>
                </div>
            )}
            {metadata.labeling && (
                <>
                    <div className="flex items-center gap-2">
                        <span className="text-tertiary">Labeling model:</span>
                        <span className="font-mono text-xs">{metadata.labeling.model}</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <span className="text-tertiary">Actionable:</span>
                        <span>{metadata.labeling.actionable ? 'Yes' : 'No'}</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <span className="text-tertiary">Segment samples:</span>
                        <span>{metadata.labeling.segment_sample_count}</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <span className="text-tertiary">Users / occurrences:</span>
                        <span>
                            {metadata.labeling.relevant_user_count} users, {metadata.labeling.occurrence_count}{' '}
                            occurrences
                        </span>
                    </div>
                </>
            )}
        </div>
    )
}

function SegmentsPanel({ segments }: { segments: SignalReportDebugSegment[] }): JSX.Element {
    if (segments.length === 0) {
        return <p className="text-sm text-tertiary m-0">No segments found in ClickHouse.</p>
    }

    return (
        <div className="space-y-1">
            {segments.map((segment) => (
                <div key={segment.document_id} className="border rounded p-2 bg-surface-primary text-xs">
                    <div className="flex items-center gap-2 mb-1">
                        <span className="font-mono truncate flex-1" title={segment.document_id}>
                            {segment.document_id}
                        </span>
                        {segment.centroid_distance !== null && (
                            <span
                                className={`font-mono ${distanceColor(segment.centroid_distance)}`}
                                title="Cosine distance to centroid"
                            >
                                d={segment.centroid_distance.toFixed(4)}
                            </span>
                        )}
                    </div>
                    {segment.content && <p className="text-secondary m-0 line-clamp-2">{segment.content}</p>}
                    <div className="flex items-center gap-3 mt-1 text-tertiary">
                        {segment.session_id && (
                            <span>
                                Session: <span className="font-mono">{segment.session_id.slice(0, 8)}...</span>
                            </span>
                        )}
                        {segment.timestamp && <span>{relativeTime(segment.timestamp)}</span>}
                    </div>
                </div>
            ))}
        </div>
    )
}

function SessionsPanel({ sessions }: { sessions: SignalReportDebugSession[] }): JSX.Element {
    if (sessions.length === 0) {
        return <p className="text-sm text-tertiary m-0">No session export data found.</p>
    }

    return (
        <div className="space-y-2">
            {sessions.map((session) => (
                <div key={session.session_id} className="border rounded p-2 bg-surface-primary text-xs">
                    <div className="flex items-center gap-2 mb-1">
                        <span className="text-tertiary">Session:</span>
                        <Link to={`/replay/${session.session_id}`} className="font-mono text-link" target="_blank">
                            {session.session_id}
                        </Link>
                    </div>
                    {session.exports.length > 0 ? (
                        <div className="space-y-1 mt-1">
                            {session.exports.map((exp) => (
                                <div key={exp.id} className="flex items-center gap-3 text-tertiary">
                                    <LemonTag size="small">{exp.export_format}</LemonTag>
                                    {exp.created_at && <span>{relativeTime(exp.created_at)}</span>}
                                    {exp.content_location && (
                                        <span className="font-mono truncate" title={exp.content_location}>
                                            {exp.content_location.split('/').pop()}
                                        </span>
                                    )}
                                    {exp.expires_after && (
                                        <span className="text-tertiary">expires {relativeTime(exp.expires_after)}</span>
                                    )}
                                </div>
                            ))}
                        </div>
                    ) : (
                        <p className="text-tertiary m-0">No exports found.</p>
                    )}
                </div>
            ))}
        </div>
    )
}

function DebugTracePanel({
    debugData,
    loading,
}: {
    debugData: SignalReportDebugResponse | undefined
    loading: boolean
}): JSX.Element {
    if (loading && !debugData) {
        return (
            <div className="flex items-center gap-2 text-sm text-tertiary py-2">
                <Spinner className="size-4" />
                Loading debug data...
            </div>
        )
    }

    if (!debugData) {
        return <p className="text-sm text-tertiary m-0">No debug data available.</p>
    }

    return (
        <div className="mt-3">
            <h4 className="text-xs font-semibold text-tertiary uppercase tracking-wide mb-2">
                Debug trace (staff only)
            </h4>
            <LemonCollapse
                multiple
                defaultActiveKeys={['pipeline', 'segments', 'sessions']}
                size="small"
                panels={[
                    {
                        key: 'pipeline',
                        header: 'Report pipeline',
                        content: debugData.pipeline_metadata ? (
                            <PipelinePanel metadata={debugData.pipeline_metadata} />
                        ) : (
                            <p className="text-sm text-tertiary m-0">No pipeline metadata recorded.</p>
                        ),
                    },
                    {
                        key: 'segments',
                        header: `Segments (${debugData.segments.length})`,
                        content: <SegmentsPanel segments={debugData.segments} />,
                    },
                    {
                        key: 'sessions',
                        header: `Sessions (${debugData.sessions.length})`,
                        content: <SessionsPanel sessions={debugData.sessions} />,
                    },
                ]}
            />
        </div>
    )
}

function ArtefactCard({ artefact }: { artefact: SignalReportArtefact }): JSX.Element {
    const content = artefact.content
    return (
        <div className="border rounded p-3 bg-surface-primary">
            <div className="flex items-center gap-2 mb-1">
                <LemonTag size="small">{artefact.type.replace('_', ' ')}</LemonTag>
                <span className="text-xs text-tertiary">{relativeTime(artefact.created_at)}</span>
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
    const { expandedReportId, artefacts, artefactsLoading, showDebugInfo, debugData, debugDataLoading } =
        useValues(inboxSceneLogic)
    const { setExpandedReportId, loadArtefacts, loadDebugData } = useActions(inboxSceneLogic)

    const isExpanded = expandedReportId === report.id
    const priority = priorityLabel(report.total_weight)
    const reportArtefacts = artefacts[report.id]

    const handleToggle = (): void => {
        if (isExpanded) {
            setExpandedReportId(null)
        } else {
            setExpandedReportId(report.id)
            if (!artefacts[report.id]) {
                loadArtefacts({ reportId: report.id })
            }
            if (showDebugInfo && !debugData[report.id]) {
                loadDebugData({ reportId: report.id })
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
                        <LemonTag type={priority.status} size="small">
                            {priority.text}
                        </LemonTag>
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
                    <span className="whitespace-nowrap">{relativeTime(report.updated_at)}</span>
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

                    {showDebugInfo && <DebugTracePanel debugData={debugData[report.id]} loading={debugDataLoading} />}
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
    const { reports, reportsLoading, reportsError } = useValues(inboxSceneLogic)
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
            ) : reportsError && reports.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-center">
                    <h3 className="text-lg font-semibold mb-1">Couldn't load reports</h3>
                    <p className="text-sm text-secondary mb-4">An error occurred while fetching your inbox.</p>
                    <LemonButton type="secondary" onClick={() => loadReports()}>
                        Try again
                    </LemonButton>
                </div>
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
