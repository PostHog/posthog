import { useActions, useValues } from 'kea'

import { IconChevronRight, IconExternal } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCollapse, LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonMarkdownWithMermaid } from 'lib/lemon-ui/LemonMarkdown/LemonMarkdownWithMermaid'

import { autoresearchPipelineLogic, trainingRunProgress } from '../autoresearchPipelineLogic'
import { type AutoresearchRunApi, AutoresearchTrainingRunApi } from '../generated/api.schemas'
import { IterationTrail } from './IterationTrail'

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
                    content: <LemonMarkdownWithMermaid>{report}</LemonMarkdownWithMermaid>,
                },
            ]}
        />
    )
}

export function TrainingRunRow({ run }: { run: AutoresearchTrainingRunApi }): JSX.Element {
    const { expandedRunId, artifactsByRun, artifactsByRunLoading } = useValues(autoresearchPipelineLogic)
    const { toggleRunArtifacts, viewArtifact } = useActions(autoresearchPipelineLogic)
    const isExpanded = expandedRunId === run.id
    const paths = artifactsByRun[run.id]
    const progress = trainingRunProgress(run)
    const startedAt = run.started_at ?? run.created_at
    const duration =
        run.started_at && run.completed_at ? dayjs(run.completed_at).from(dayjs(run.started_at), true) : null
    const runStatus = RUN_STATUS[run.status]
    const progressSummary =
        run.status === 'failed' && progress.iterationCount === 0
            ? 'Failed before any iterations'
            : `${progress.iterationCount} iterations · ${
                  progress.bestHoldoutScore != null
                      ? `best AUC ${progress.bestHoldoutScore.toFixed(3)}`
                      : 'no score yet'
              }`

    return (
        <div className="border rounded">
            <div className="p-3 flex justify-between items-center">
                <div className="flex items-center gap-2">
                    <LemonButton
                        size="small"
                        icon={<IconChevronRight className={`transition-transform ${isExpanded ? 'rotate-90' : ''}`} />}
                        onClick={() => toggleRunArtifacts(run.id)}
                        tooltip={isExpanded ? 'Hide details' : 'Show iterations & bundle'}
                    />
                    <div className="space-y-0.5">
                        <div className="text-sm font-semibold flex items-center gap-1">
                            <Tooltip title={dayjs(startedAt).format('MMM D, YYYY HH:mm')}>
                                <span>Training run · {dayjs(startedAt).fromNow()}</span>
                            </Tooltip>
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
                            {run.status === 'running' && <Spinner className="ml-2 inline" />}
                        </div>
                        <div className="text-xs text-muted">
                            <span className="font-mono">{run.id.slice(0, 8)}</span> · {progressSummary}
                            {duration ? ` · took ${duration}` : ''}
                        </div>
                    </div>
                </div>
                <LemonTag type={runStatus.type}>{runStatus.label}</LemonTag>
            </div>
            {isExpanded && (
                <div className="border-t p-3 space-y-3">
                    {run.status === 'failed' && run.error && <LemonBanner type="error">{run.error}</LemonBanner>}
                    <RunReport runId={run.id} />
                    <div className="space-y-2">
                        <div className="text-xs font-semibold text-muted uppercase tracking-wide">Iterations</div>
                        <IterationTrail iterations={run.iterations} />
                    </div>
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
        </div>
    )
}
