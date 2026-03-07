import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTable, Tooltip } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { IconCancel } from 'lib/lemon-ui/icons'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { BatchExportBackfill } from '~/types'

import { BatchExportBackfillModal } from './BatchExportBackfillModal'
import { BatchExportBackfillsLogicProps, batchExportBackfillsLogic } from './batchExportBackfillsLogic'

export function BatchExportBackfills({ id }: BatchExportBackfillsLogicProps): JSX.Element {
    const logic = batchExportBackfillsLogic({ id })
    const { batchExportConfig } = useValues(logic)

    if (!batchExportConfig) {
        return <NotFound object="batch export" />
    }

    return (
        <div className="flex flex-col gap-2">
            <BatchExportBackfillsControls id={id} />
            <BatchExportLatestBackfills id={id} />
            <BatchExportBackfillModal id={id} />
        </div>
    )
}

function BatchExportBackfillsControls({ id }: BatchExportBackfillsLogicProps): JSX.Element {
    const logic = batchExportBackfillsLogic({ id })
    const { loading } = useValues(logic)
    const { loadBackfills, openBackfillModal } = useActions(logic)

    return (
        <div className="flex gap-2 items-center justify-between">
            <LemonButton onClick={loadBackfills} loading={loading} type="secondary" icon={<IconRefresh />} size="small">
                Refresh
            </LemonButton>

            <LemonButton type="primary" onClick={() => openBackfillModal()}>
                Start backfill
            </LemonButton>
        </div>
    )
}

function BatchExportLatestBackfills({ id }: BatchExportBackfillsLogicProps): JSX.Element {
    const logic = batchExportBackfillsLogic({ id })
    const { latestBackfills, loading, hasMoreBackfillsToLoad, batchExportConfig } = useValues(logic)
    const { cancelBackfill, loadOlderBackfills, openBackfillModal } = useActions(logic)

    if (!batchExportConfig) {
        return <NotFound object="batch export" />
    }

    return (
        <>
            <LemonTable
                dataSource={latestBackfills}
                loading={loading}
                loadingSkeletonRows={5}
                footer={
                    hasMoreBackfillsToLoad && (
                        <div className="flex items-center m-2">
                            <LemonButton center fullWidth onClick={loadOlderBackfills} loading={loading}>
                                Load more rows
                            </LemonButton>
                        </div>
                    )
                }
                columns={[
                    {
                        title: 'Status',
                        key: 'status',
                        width: 0,
                        render: (_, backfill) => {
                            const status = backfill.status
                            const color = colorForStatus(status)
                            const statusStyles = {
                                success: 'border-success text-success-dark',
                                'color-accent': 'border-accent text-accent',
                                warning: 'border-warning text-warning-dark',
                                danger: 'border-danger text-danger-dark',
                                default: 'border-default text-default-dark',
                            } as const
                            return (
                                <span
                                    className={clsx(
                                        'flex justify-center items-center p-2 h-6 text-xs font-semibold rounded-full border-2 select-none',
                                        statusStyles[color]
                                    )}
                                >
                                    <span className="text-center">{status}</span>
                                </span>
                            )
                        },
                    },
                    {
                        title: 'Progress',
                        key: 'progress',
                        render: (_, backfill) => {
                            const status = backfill.status
                            const color = colorForStatus(status)
                            const progress = backfill.progress
                            if (progress && progress.progress != null) {
                                let label = ''
                                if (progress.finished_runs != null && progress.total_runs != null) {
                                    if (progress.total_runs === 0) {
                                        label = '(0 runs)'
                                    } else {
                                        const runsLabel = progress.total_runs === 1 ? 'run' : 'runs'
                                        label = `(${progress.finished_runs}/${progress.total_runs} ${runsLabel})`
                                    }
                                }

                                return (
                                    <span className="flex gap-2 items-center">
                                        <LemonProgress
                                            percent={progress.progress * 100}
                                            strokeColor={`var(--${color})`}
                                            className="min-w-[80px]"
                                        />
                                        <span className="flex-shrink-0 whitespace-nowrap">{label}</span>
                                    </span>
                                )
                            }
                            return ''
                        },
                    },
                    {
                        title: 'ID',
                        key: 'runId',
                        render: (_, backfill) => backfill.id,
                    },
                    {
                        title: 'Total rows',
                        key: 'total_records_count',
                        render: (_, backfill) => {
                            if (backfill.total_records_count == null) {
                                return ''
                            }
                            const isEstimate = backfill.status === 'Running' || backfill.status === 'Starting'
                            const formatted = backfill.total_records_count.toLocaleString()
                            if (isEstimate) {
                                return (
                                    <Tooltip title="Estimated count, may change as the backfill progresses">
                                        <div className="cursor-help border-b border-dashed border-current w-fit">
                                            ~{formatted}
                                        </div>
                                    </Tooltip>
                                )
                            }
                            return formatted
                        },
                    },
                    {
                        title: 'Interval start',
                        key: 'intervalStart',
                        tooltip: 'Start of the time range to backfill',
                        render: (_, backfill) => {
                            return backfill.start_at ? (
                                <TZLabel time={backfill.start_at} formatDate="MMMM DD, YYYY" formatTime="HH:mm:ss" />
                            ) : (
                                'Beginning of time'
                            )
                        },
                    },
                    {
                        title: 'Interval end',
                        key: 'intervalEnd',
                        tooltip: 'End of the time range to backfill',
                        render: (_, backfill) => {
                            return backfill.end_at ? (
                                <TZLabel time={backfill.end_at} formatDate="MMMM DD, YYYY" formatTime="HH:mm:ss" />
                            ) : (
                                'Until present'
                            )
                        },
                    },
                    {
                        title: 'Started',
                        key: 'started',
                        tooltip: 'Date and time when this BatchExport backfill started',
                        render: (_, backfill) => (backfill.created_at ? <TZLabel time={backfill.created_at} /> : ''),
                    },
                    {
                        title: 'Finished',
                        key: 'finished',
                        tooltip: 'Date and time when this BatchExport backfill finished',
                        render: (_, backfill) => (backfill.finished_at ? <TZLabel time={backfill.finished_at} /> : ''),
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: function RenderActions(_, backfill) {
                            if (backfillIsCancelable(backfill.status)) {
                                return (
                                    <div className="flex gap-1">
                                        <BackfillCancelButton backfill={backfill} cancelBackfill={cancelBackfill} />
                                    </div>
                                )
                            }
                        },
                    },
                ]}
                emptyState={
                    <div className="deprecated-space-y-2">
                        <div>No backfills in this time range.</div>
                        <LemonButton type="primary" onClick={() => openBackfillModal()}>
                            Start backfill
                        </LemonButton>
                    </div>
                }
            />
        </>
    )
}

function BackfillCancelButton({
    backfill,
    cancelBackfill,
}: {
    backfill: BatchExportBackfill
    cancelBackfill: (backfill: BatchExportBackfill) => void
}): JSX.Element {
    return (
        <span className="flex gap-1 items-center">
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconCancel />}
                tooltip="Cancel backfill"
                onClick={() =>
                    LemonDialog.open({
                        title: 'Cancel backfill?',
                        description: (
                            <>
                                <p>This will cancel the selected backfill.</p>
                            </>
                        ),
                        width: '20rem',
                        primaryButton: {
                            children: 'Cancel backfill',
                            onClick: () => cancelBackfill(backfill),
                        },
                        secondaryButton: {
                            children: 'Go back',
                        },
                    })
                }
            />
        </span>
    )
}

const colorForStatus = (
    status: BatchExportBackfill['status']
): 'success' | 'color-accent' | 'warning' | 'danger' | 'default' => {
    switch (status) {
        case 'Completed':
            return 'success'
        case 'ContinuedAsNew':
        case 'Running':
        case 'Starting':
            return 'color-accent'
        case 'Cancelled':
        case 'Terminated':
        case 'TimedOut':
            return 'warning'
        case 'Failed':
        case 'FailedRetryable':
            return 'danger'
        default:
            return 'default'
    }
}

const backfillIsCancelable = (status: BatchExportBackfill['status']): boolean => {
    return status === 'Running' || status === 'Starting'
}
