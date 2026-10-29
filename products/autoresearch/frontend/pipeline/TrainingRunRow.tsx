import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconChevronRight, IconExternal, IconNotebook } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCollapse, LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonMarkdownWithMermaid } from 'lib/lemon-ui/LemonMarkdown/LemonMarkdownWithMermaid'
import { urls } from 'scenes/urls'

import { runHeadline } from '../agentSearch'
import { autoresearchPipelineLogic, trainingRunProgress } from '../autoresearchPipelineLogic'
import {
    type AutoresearchRunApi,
    AutoresearchTrainingRunApi,
    type AutoresearchTrainingRunKickoffReasonEnumApi,
} from '../generated/api.schemas'
import { RunFeatureComparison } from './RunFeatureComparison'

// Derived from the field rather than the standalone enum: this pending/running/completed/failed
// set is shared with another product, so the generated enum does not carry an autoresearch name.
type AutoresearchRunStatus = NonNullable<AutoresearchRunApi['status']>

const RUN_STATUS: Record<
    AutoresearchRunStatus,
    { type: 'success' | 'default' | 'danger' | 'highlight'; label: string }
> = {
    pending: { type: 'default', label: 'Pending' },
    running: { type: 'highlight', label: 'Running' },
    completed: { type: 'success', label: 'Completed' },
    failed: { type: 'danger', label: 'Failed' },
}

const KICKOFF_REASON: Record<AutoresearchTrainingRunKickoffReasonEnumApi, { label: string; tooltip: string }> = {
    explore: { label: 'Exploring', tooltip: 'One of the first daily runs that look for a better model' },
    scheduled: { label: 'Scheduled', tooltip: 'Started on the research schedule set on the Setup tab' },
    rescue: { label: 'Rescue', tooltip: 'A short run to replace a model that stopped scoring' },
    manual: { label: 'Manual', tooltip: 'Started by a person or an agent' },
}

/** The agent-authored report.md for a run, rendered as markdown (with mermaid charts). */
function RunReport({ runId }: { runId: string }): JSX.Element | null {
    const { reportByRun, reportByRunLoading } = useValues(autoresearchPipelineLogic)
    const report = reportByRun[runId]
    if (report === undefined) {
        return reportByRunLoading ? <Spinner /> : null
    }
    if (!report) {
        // Loaded, but the agent uploaded no report.md — show nothing; iterations/bundle still render.
        return null
    }
    return (
        <LemonCollapse
            panels={[
                {
                    key: 'report',
                    header: 'Report',
                    // The agent writes this report, so a remote image in it would make the viewer's browser call that host.
                    content: <LemonMarkdownWithMermaid disableImages="all">{report}</LemonMarkdownWithMermaid>,
                },
            ]}
        />
    )
}

const RUN_ROLE = {
    live: { type: 'completion', label: 'Live model' },
    scored_alongside: { type: 'highlight', label: 'Scored alongside' },
} as const

/** One training run in the log: its headline, the experiments passed as children, and its report and bundle on expand. */
export function TrainingRunRow({
    run,
    runNumber,
    children,
}: {
    run: AutoresearchTrainingRunApi
    runNumber: number
    children?: ReactNode
}): JSX.Element {
    const { expandedRunId, artifactsByRun, artifactsByRunLoading, featureFlags, runRoles } =
        useValues(autoresearchPipelineLogic)
    const { toggleRunArtifacts, viewArtifact, reportNotebookOpened } = useActions(autoresearchPipelineLogic)
    const reportNotebookShortId = featureFlags[FEATURE_FLAGS.AUTORESEARCH_REPORT_NOTEBOOK]
        ? run.summary?.report_notebook_short_id
        : undefined
    const isExpanded = expandedRunId === run.id
    const paths = artifactsByRun[run.id]
    const progress = trainingRunProgress(run)
    const startedAt = run.started_at ?? run.created_at
    const duration =
        run.started_at && run.completed_at ? dayjs(run.completed_at).from(dayjs(run.started_at), true) : null
    const runStatus = RUN_STATUS[run.status]
    const role = runRoles[run.id] ? RUN_ROLE[runRoles[run.id]] : null
    const { headline, detail } = runHeadline(run, runNumber)
    const improved = run.iterations.filter((it) => it.status === 'kept').length
    const progressSummary =
        run.status === 'failed' && progress.iterationCount === 0
            ? 'Failed before any experiments'
            : `${progress.iterationCount} ${progress.iterationCount === 1 ? 'experiment' : 'experiments'}, ${improved} improved`

    return (
        <div className="border rounded">
            <div className="p-3 flex items-start gap-2">
                <LemonButton
                    size="small"
                    icon={<IconChevronRight className={`transition-transform ${isExpanded ? 'rotate-90' : ''}`} />}
                    onClick={() => toggleRunArtifacts(run.id)}
                    tooltip={isExpanded ? 'Hide report and bundle' : 'Show report and bundle'}
                />
                <div className="flex-1 min-w-0 space-y-0.5">
                    <div className="flex items-center gap-2 min-w-0">
                        <span className="text-sm font-semibold truncate flex-1 min-w-0" title={headline}>
                            {headline}
                        </span>
                        {progress.bestHoldoutScore != null && (
                            <span className="text-sm font-semibold tabular-nums shrink-0">
                                {progress.bestHoldoutScore.toFixed(3)}
                            </span>
                        )}
                    </div>
                    <div className="flex flex-wrap items-center gap-x-1 gap-y-1 text-xs text-muted">
                        <Tooltip title={dayjs(startedAt).format('MMM D, YYYY HH:mm')}>
                            <span>
                                {run.reader_summary?.trim() ? `Run ${runNumber} · ` : ''}
                                {dayjs(startedAt).format('MMM D')} · {progressSummary}
                                {duration ? ` · ${duration}` : ''}
                            </span>
                        </Tooltip>
                        {run.kickoff_reason && (
                            <Tooltip title={KICKOFF_REASON[run.kickoff_reason].tooltip}>
                                <span>· {KICKOFF_REASON[run.kickoff_reason].label}</span>
                            </Tooltip>
                        )}
                        {run.agent_model_label && (
                            <Tooltip title="The model the research agent ran on">
                                <span>· {run.agent_model_label}</span>
                            </Tooltip>
                        )}
                        {run.task_url && (
                            <Link
                                to={run.task_url}
                                target="_blank"
                                className="text-muted hover:text-primary"
                                title="Open sandbox task"
                            >
                                <IconExternal className="text-sm" />
                            </Link>
                        )}
                        {run.status === 'running' && <Spinner className="inline" />}
                        {role && (
                            <LemonTag type={role.type} size="small">
                                {role.label}
                            </LemonTag>
                        )}
                        {run.status !== 'completed' && (
                            <LemonTag type={runStatus.type} size="small">
                                {runStatus.label}
                            </LemonTag>
                        )}
                    </div>
                    {detail && <div className="text-xs text-secondary">{detail}</div>}
                </div>
            </div>
            {isExpanded && (
                <div className="border-t p-3 space-y-3">
                    {run.status === 'failed' && run.error && <LemonBanner type="error">{run.error}</LemonBanner>}
                    {reportNotebookShortId ? (
                        <Link
                            to={urls.notebook(reportNotebookShortId)}
                            onClick={() => reportNotebookOpened(run.id)}
                            data-attr="autoresearch-report-notebook-link"
                            className="inline-flex items-center gap-1 text-sm"
                        >
                            <IconNotebook />
                            Open report notebook
                        </Link>
                    ) : (
                        <RunReport runId={run.id} />
                    )}
                    {run.status === 'completed' && (
                        <div className="space-y-2">
                            <div className="text-xs font-semibold text-muted uppercase tracking-wide">
                                What drives it
                            </div>
                            <RunFeatureComparison runId={run.id} />
                        </div>
                    )}
                    {run.summary && (
                        <div className="space-y-1">
                            <div className="text-xs font-semibold text-muted uppercase tracking-wide">
                                What the agent learned
                            </div>
                            {run.summary.distillation && (
                                <div className="text-sm text-default italic">"{run.summary.distillation}"</div>
                            )}
                            {run.summary.recommended_next && (
                                <div className="text-xs text-muted">Next: {run.summary.recommended_next}</div>
                            )}
                        </div>
                    )}
                    <div className="space-y-2">
                        <div className="text-xs font-semibold text-muted uppercase tracking-wide">Artifact bundle</div>
                        {paths === undefined && artifactsByRunLoading ? (
                            <Spinner />
                        ) : paths && paths.length > 0 ? (
                            <div className="flex flex-wrap gap-2">
                                {paths.map((path) => (
                                    <LemonButton
                                        key={path}
                                        type="secondary"
                                        size="small"
                                        onClick={() => viewArtifact({ runId: run.id, path })}
                                    >
                                        {path}
                                    </LemonButton>
                                ))}
                            </div>
                        ) : (
                            <div className="text-muted text-sm">No artifacts uploaded for this run.</div>
                        )}
                    </div>
                </div>
            )}
            {children}
        </div>
    )
}
