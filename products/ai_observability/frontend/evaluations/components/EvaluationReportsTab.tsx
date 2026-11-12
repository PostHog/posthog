import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { LemonButton, LemonTable, Link } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { reportText } from '../create/evaluationSummary'
import { evaluationReportDrawerLogic } from '../evaluationReportDrawerLogic'
import { draftFromReport, evaluationReportLogic } from '../evaluationReportLogic'
import { evaluationReportTracking } from '../evaluationReportTracking'
import type { EvaluationReportRun } from '../types'
import { DeliveryTargetsConfig } from './DeliveryTargetsConfig'
import { ReportDeliveryTag } from './ReportDeliveryTag'
import { reportDestinationsText } from './reportDestinationsText'
import { headlineChange, reportHeadline } from './reportHeadline'
import { ReportResultBar } from './ReportResultBar'

interface EvaluationReportsTabProps {
    evaluationId: string
    generationDisabledReason?: string
    userAccessLevel?: AccessControlLevel
    /** Called when the user clicks the "Set up scheduled reports" CTA in the empty state. */
    onConfigureClick: () => void
}

function HeadlineCell({ run }: { run: EvaluationReportRun }): JSX.Element {
    const headline = reportHeadline(run)
    if (!headline) {
        return <span className="text-secondary">–</span>
    }
    const change = headlineChange(headline)
    return (
        <div className="flex w-36 flex-col gap-1.5">
            <span className="tabular-nums whitespace-nowrap">
                <span className="font-semibold">{`${headline.value.toFixed(1)}%`}</span>
                {change && (
                    <span className={cn('ml-1.5 text-xs font-medium', change.className)}>
                        {`${change.change > 0 ? '▲' : '▼'} ${Math.abs(change.change).toFixed(1)}pp`}
                    </span>
                )}
            </span>
            <ReportResultBar segments={headline.segments} />
        </div>
    )
}

export function EvaluationReportsTab({
    evaluationId,
    generationDisabledReason,
    userAccessLevel,
    onConfigureClick,
}: EvaluationReportsTabProps): JSX.Element {
    const logic = evaluationReportLogic({ evaluationId })
    const {
        reportRuns,
        reportRunsLoading,
        reportsLoading,
        reportsLoadFailed,
        reportRunsLoadFailed,
        activeReport,
        generateResultLoading,
        waitingForNewReportSince,
        hasOlderReportRuns,
        configDraft,
        shownDestinations,
    } = useValues(logic)
    const {
        generateReport,
        loadReports,
        loadReportRuns,
        loadOlderReportRuns,
        saveDestinations,
        setDraftEmailValue,
        setDraftSlackIntegrationId,
        setDraftSlackChannelValue,
        addDraftDestination,
        removeDraftDestination,
    } = useActions(logic)
    const { openRunId } = useValues(evaluationReportDrawerLogic({ evaluationId }))
    const { openRun } = useActions(evaluationReportDrawerLogic({ evaluationId }))
    const [editingDestinations, setEditingDestinations] = useState(false)

    const tracked = useRef(false)
    useEffect(() => {
        if (!tracked.current && activeReport && !reportRunsLoading) {
            tracked.current = true
            evaluationReportTracking.tabViewed({
                report_count: reportRuns.length,
                has_destination: activeReport.delivery_targets.length > 0,
                enabled: activeReport.enabled,
            })
        }
    }, [activeReport, reportRunsLoading, reportRuns.length])

    if (reportsLoadFailed) {
        return (
            <div className="max-w-6xl flex items-center gap-2 rounded border p-4 text-sm">
                <span>Couldn't load the reports.</span>
                <LemonButton size="small" type="secondary" onClick={() => loadReports()}>
                    Try again
                </LemonButton>
            </div>
        )
    }

    // No schedule configured at all → CTA pointing to the Configuration tab.
    // Avoids hiding the Reports tab entirely so it stays discoverable.
    if (!reportsLoading && !activeReport) {
        return (
            <div className="max-w-6xl">
                <div className="bg-bg-light border rounded p-8 text-center space-y-3">
                    <h3 className="text-lg font-semibold m-0">No scheduled reports yet</h3>
                    <p className="text-muted text-sm m-0">
                        {generationDisabledReason ??
                            "Scheduled reports deliver AI-generated analysis of this evaluation's results to email or Slack on a recurring basis."}
                    </p>
                    <LemonButton type="primary" onClick={onConfigureClick}>
                        {generationDisabledReason ? 'Configure evaluation' : 'Set up scheduled reports'}
                    </LemonButton>
                </div>
            </div>
        )
    }

    const isWriting = generateResultLoading || !!waitingForNewReportSince
    const savedDraft = activeReport ? draftFromReport(activeReport) : null

    return (
        <div className="@container max-w-6xl flex flex-col gap-4">
            {activeReport && savedDraft && (
                <div className="flex flex-col gap-3">
                    <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
                        <p className="m-0 min-w-0 flex-1 basis-64 text-sm text-secondary">
                            {activeReport.enabled
                                ? `Reports ${reportText({ ...savedDraft, cooldownMinutes: activeReport.cooldown_minutes })}`
                                : 'Reports are off'}
                            {' · '}
                            {reportDestinationsText(activeReport.delivery_targets)}
                            {!editingDestinations && (
                                <>
                                    {' · '}
                                    <AccessControlAction
                                        resourceType={AccessControlResourceType.Evaluation}
                                        minAccessLevel={AccessControlLevel.Editor}
                                        userAccessLevel={userAccessLevel}
                                    >
                                        <Link
                                            onClick={() => setEditingDestinations(true)}
                                            data-attr="llma-evaluation-report-edit-destinations"
                                        >
                                            Edit destinations
                                        </Link>
                                    </AccessControlAction>
                                </>
                            )}
                        </p>
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Evaluation}
                            minAccessLevel={AccessControlLevel.Editor}
                            userAccessLevel={userAccessLevel}
                        >
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => generateReport(activeReport.id)}
                                loading={isWriting}
                                disabledReason={generationDisabledReason}
                                data-attr="llma-evaluation-report-generate"
                            >
                                Generate now
                            </LemonButton>
                        </AccessControlAction>
                    </div>
                    {editingDestinations && (
                        <div className="@container/evaluation flex flex-col gap-3 rounded border p-3">
                            <DeliveryTargetsConfig
                                emailValue={configDraft.emailValue}
                                onEmailChange={setDraftEmailValue}
                                slackIntegrationId={configDraft.slackIntegrationId}
                                onSlackIntegrationChange={setDraftSlackIntegrationId}
                                slackChannelValue={configDraft.slackChannelValue}
                                onSlackChannelChange={setDraftSlackChannelValue}
                                shown={shownDestinations}
                                onAdd={addDraftDestination}
                                onRemove={removeDraftDestination}
                            />
                            <div className="flex gap-2">
                                <LemonButton
                                    type="primary"
                                    size="small"
                                    loading={reportsLoading}
                                    onClick={() => {
                                        saveDestinations()
                                        setEditingDestinations(false)
                                    }}
                                    data-attr="llma-evaluation-report-save-destinations"
                                >
                                    Save destinations
                                </LemonButton>
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    onClick={() => {
                                        // Restores only the destinations, so other unsaved settings stay as typed.
                                        setDraftEmailValue(savedDraft.emailValue)
                                        setDraftSlackIntegrationId(savedDraft.slackIntegrationId)
                                        setDraftSlackChannelValue(savedDraft.slackChannelValue)
                                        setEditingDestinations(false)
                                    }}
                                >
                                    Cancel
                                </LemonButton>
                            </div>
                        </div>
                    )}
                    {isWriting && (
                        <p className="m-0 text-sm text-secondary">Writing a new report. This can take a few minutes.</p>
                    )}
                </div>
            )}

            {reportRunsLoadFailed ? (
                <div className="flex items-center gap-2 rounded border p-4 text-sm">
                    <span>Couldn't load the reports.</span>
                    {activeReport && (
                        <LemonButton size="small" type="secondary" onClick={() => loadReportRuns(activeReport.id)}>
                            Try again
                        </LemonButton>
                    )}
                </div>
            ) : (
                <LemonTable
                    dataSource={reportRuns}
                    loading={reportsLoading || reportRunsLoading}
                    rowKey="id"
                    onRow={(run) => ({ onClick: () => openRun(run.id, 'reports_tab') })}
                    rowClassName={(run) =>
                        run.id === openRunId ? 'LemonTable__row--status-highlighted cursor-pointer' : 'cursor-pointer'
                    }
                    columns={[
                        {
                            title: 'Report',
                            key: 'title',
                            render: (_, run) => (
                                <div className="flex flex-col min-w-0 py-1">
                                    <TZLabel
                                        time={run.period_end}
                                        noStyles
                                        className="text-xs text-secondary"
                                        formatDate="MMM D"
                                        formatTime="HH:mm"
                                    />
                                    <span className="font-medium truncate max-w-xl" title={run.content?.title}>
                                        {run.content?.title || 'Evaluation report'}
                                    </span>
                                </div>
                            ),
                        },
                        {
                            title: 'Result',
                            key: 'headline',
                            render: (_, run) => <HeadlineCell run={run} />,
                        },
                        {
                            title: 'Results',
                            key: 'total_runs',
                            align: 'right',
                            className: 'hidden @min-[40rem]:table-cell',
                            render: (_, run) => run.content?.metrics?.total_runs ?? run.metadata?.total_runs ?? '–',
                        },
                        {
                            title: 'Delivery',
                            key: 'delivery_status',
                            className: 'hidden @min-[32.5rem]:table-cell',
                            render: (_, run) => <ReportDeliveryTag run={run} />,
                        },
                    ]}
                    emptyState={
                        activeReport?.frequency === 'every_n'
                            ? `No report yet. The first one arrives after ${activeReport.trigger_threshold ?? 100} new results.`
                            : 'No report yet.'
                    }
                    size="small"
                />
            )}

            {hasOlderReportRuns && !reportRunsLoadFailed && (
                <div className="flex justify-center">
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => loadOlderReportRuns()}
                        loading={reportRunsLoading}
                        data-attr="llma-evaluation-report-show-older"
                    >
                        Show older reports
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
