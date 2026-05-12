import { useActions, useValues } from 'kea'

import { IconClock, IconEllipsis, IconEye, IconPlay, IconPause, IconRefresh, IconTrash } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonDrawer, LemonMenu, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { WatchedQuestion, WatchedQuestionSeverity, watchedQuestionsLogic } from './watchedQuestionsLogic'

const SEVERITY_TAG: Record<
    WatchedQuestionSeverity,
    { label: string; type: 'success' | 'highlight' | 'warning' | 'danger' }
> = {
    none: { label: 'No drift', type: 'success' },
    minor: { label: 'Minor', type: 'highlight' },
    moderate: { label: 'Moderate', type: 'warning' },
    significant: { label: 'Significant', type: 'danger' },
}

function latestSeverity(question: WatchedQuestion): WatchedQuestionSeverity {
    const latestRun = question.recent_runs[0]
    return latestRun?.severity || 'none'
}

function relativeTime(iso: string | null): string {
    if (!iso) {
        return 'never'
    }
    const date = new Date(iso)
    const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000))
    if (seconds < 60) {
        return `${seconds}s ago`
    }
    if (seconds < 3600) {
        return `${Math.floor(seconds / 60)}m ago`
    }
    if (seconds < 86_400) {
        return `${Math.floor(seconds / 3600)}h ago`
    }
    return `${Math.floor(seconds / 86_400)}d ago`
}

export function WatchedQuestionsPanel(): JSX.Element {
    const { panelOpen, watchedQuestions, watchedQuestionsLoading } = useValues(watchedQuestionsLogic)
    const { closePanel, pauseQuestion, resumeQuestion, runNow, archiveQuestion } = useActions(watchedQuestionsLogic)

    return (
        <LemonDrawer
            isOpen={panelOpen}
            onClose={closePanel}
            title="Watched questions"
            description="Max re-runs these questions on a schedule and emits a Signal when the answer materially changes."
            placement="right"
            width={520}
        >
            {watchedQuestions.length === 0 && !watchedQuestionsLoading ? (
                <div className="flex flex-col items-center justify-center gap-2 p-8 text-center">
                    <IconEye className="text-3xl text-muted" />
                    <p className="font-medium">No watched questions yet</p>
                    <p className="text-muted">Click the bell on any Max answer to start watching it for changes.</p>
                </div>
            ) : (
                <LemonTable
                    loading={watchedQuestionsLoading}
                    dataSource={watchedQuestions}
                    rowKey="id"
                    expandable={{
                        rowExpandable: (row) => row.recent_runs.length > 0,
                        expandedRowRender: (row) => (
                            <div className="flex flex-col gap-1 p-2 text-sm">
                                {row.recent_runs.map((run) => {
                                    const tag = SEVERITY_TAG[run.severity]
                                    return (
                                        <div key={run.id} className="flex items-center gap-2">
                                            <LemonTag type={tag.type}>{tag.label}</LemonTag>
                                            <span className="text-muted">{relativeTime(run.created_at)}</span>
                                            <span>{run.judge_summary || run.error || '—'}</span>
                                        </div>
                                    )
                                })}
                            </div>
                        ),
                    }}
                    columns={[
                        {
                            title: 'Question',
                            key: 'title',
                            render: (_, row) => (
                                <div className="flex flex-col">
                                    <span className="font-medium">{row.title}</span>
                                    <span className="text-xs text-muted line-clamp-1">{row.question_text}</span>
                                </div>
                            ),
                        },
                        {
                            title: 'Cadence',
                            key: 'cadence',
                            width: 90,
                            render: (_, row) => <LemonTag>{row.cadence}</LemonTag>,
                        },
                        {
                            title: 'Last run',
                            key: 'last_run',
                            width: 100,
                            render: (_, row) => (
                                <div className="flex items-center gap-1 text-muted">
                                    <IconClock />
                                    <span>{relativeTime(row.last_run_at)}</span>
                                </div>
                            ),
                        },
                        {
                            title: 'Drift',
                            key: 'severity',
                            width: 110,
                            render: (_, row) => {
                                const severity = latestSeverity(row)
                                const tag = SEVERITY_TAG[severity]
                                return (
                                    <div className="flex items-center gap-1">
                                        <LemonBadge.Number
                                            count={row.recent_runs.filter((r) => r.state === 'drifted').length}
                                            status={severity === 'significant' ? 'danger' : 'muted'}
                                        />
                                        <LemonTag type={tag.type}>{tag.label}</LemonTag>
                                    </div>
                                )
                            },
                        },
                        {
                            title: '',
                            key: 'actions',
                            width: 40,
                            render: (_, row) => (
                                <LemonMenu
                                    items={[
                                        row.status === 'active'
                                            ? {
                                                  label: 'Pause',
                                                  icon: <IconPause />,
                                                  onClick: () => pauseQuestion(row.id),
                                              }
                                            : {
                                                  label: 'Resume',
                                                  icon: <IconPlay />,
                                                  onClick: () => resumeQuestion(row.id),
                                              },
                                        {
                                            label: 'Run drift check now',
                                            icon: <IconRefresh />,
                                            onClick: () => runNow(row.id),
                                        },
                                        {
                                            label: 'Archive',
                                            icon: <IconTrash />,
                                            status: 'danger',
                                            onClick: () => archiveQuestion(row.id),
                                        },
                                    ]}
                                >
                                    <LemonButton size="xsmall" icon={<IconEllipsis />} />
                                </LemonMenu>
                            ),
                        },
                    ]}
                />
            )}
        </LemonDrawer>
    )
}
