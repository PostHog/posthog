import { useActions, useValues } from 'kea'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTag, LemonTagPropsType } from 'lib/lemon-ui/LemonTag/LemonTag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ChangeExportRunStatusEnum, BatchExportRunType } from './types'
import { NewConnectionLogic } from './NewConnectionLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from '@posthog/lemon-ui'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { Progress } from 'antd'
import { ExportRun } from './ExportRun'

export enum BatchExportStatus {
    Running = 'Running',
    Cancelled = 'Cancelled',
    Completed = 'Completed',
    ContinuedAsNew = 'ContinuedAsNew',
    Failed = 'Failed',
    Terminated = 'Terminated',
    TimedOut = 'TimedOut',
    Starting = 'Starting',
    Paused = 'Paused',
}

export function StatusToTagType(status: BatchExportRunType['status']): LemonTagPropsType {
    switch (status) {
        case BatchExportStatus.Running:
            return 'highlight'
        case BatchExportStatus.Cancelled:
            return 'warning'
        case BatchExportStatus.Completed:
            return 'success'
        case BatchExportStatus.ContinuedAsNew:
            return 'highlight' // TODO: understand what this does and choose a more appropriate color
        case BatchExportStatus.Failed:
            return 'danger'
        case BatchExportStatus.Terminated:
            return 'danger'
        case BatchExportStatus.TimedOut:
            return 'danger'
        case BatchExportStatus.Starting:
            return 'highlight'
        case BatchExportStatus.Paused:
            return 'purple'
        default:
            return 'default'
    }
}

export function ExportOverviewTab(): JSX.Element {
    const { exportRuns, exportRunsLoading } = useValues(NewConnectionLogic)
    const { changeExportRunStatus } = useActions(NewConnectionLogic)
    // const { historicalExports, historicalExportsLoading, pluginConfig, interfaceJobsProps, hasRunningExports } =
    // useValues(appMetricsSceneLogic)
    // const { openHistoricalExportModal, loadHistoricalExports } = useActions(appMetricsSceneLogic)

    // useEffect(() => {
    //     let timer: NodeJS.Timeout | undefined

    //     function updateTimer(): void {
    //         if (hasRunningExports) {
    //             timer = setTimeout(() => {
    //                 loadHistoricalExports()
    //                 updateTimer()
    //             }, RELOAD_HISTORICAL_EXPORTS_FREQUENCY_MS)
    //         }
    //     }

    //     updateTimer()
    //     return () => timer && clearTimeout(timer)
    // }, [hasRunningExports])

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-end space-x-4">
                <LemonButton type="secondary">
                    {' '}
                    {/*</div>onClick={openHistoricalExportModal} disabled={!interfaceJobsProps}> */}
                    Re-run all failed runs
                </LemonButton>
                <LemonButton type="primary">
                    {' '}
                    {/*</div>onClick={openHistoricalExportModal} disabled={!interfaceJobsProps}> */}
                    Start manual export
                </LemonButton>
            </div>

            <LemonTable
                dataSource={exportRuns}
                loading={exportRunsLoading}
                columns={[
                    {
                        title: 'Created at',
                        dataIndex: 'created_at',
                        render: function RenderCreatedAt(created_at) {
                            return created_at ? (
                                <div className="whitespace-nowrap">
                                    <TZLabel time={created_at} formatDate="MMM D, YYYY" formatTime="HH:mm" />
                                </div>
                            ) : (
                                <span className="text-muted">—</span>
                            )
                        },
                        sorter: (a, b) => (new Date(a.created_at || 0) > new Date(b.created_at || 0) ? 1 : -1),
                    },
                    {
                        title: 'Event count',
                        render: function Render(_, exportRun: BatchExportRunType) {
                            return (
                                exportRun.metrics?.totals.successes + exportRun.metrics?.totals.successes_on_retry || (
                                    <div className="text-muted">—</div>
                                )
                            )
                        },
                    },
                    {
                        title: 'Event range',
                        render: function Render(_, exportRun: BatchExportRunType) {
                            return exportRun.filters
                        },
                    },
                    {
                        title: 'Status',
                        render: function Render(_, exportRun: BatchExportRunType) {
                            return (
                                <>
                                    {exportRun.status === BatchExportStatus.Running ? (
                                        <Progress percent={Math.floor((exportRun.progress || 0) * 100)} />
                                    ) : (
                                        <LemonTag type={StatusToTagType(exportRun.status)} className="uppercase">
                                            {exportRun.status}
                                        </LemonTag>
                                    )}
                                </>
                            )
                        },
                    },
                    {
                        title: 'Created by',
                        render: function Render(_, exportRun: BatchExportRunType) {
                            if (exportRun.export_schedule_id) {
                                return <div>Scheduler</div>
                            } else {
                                const { created_by } = exportRun
                                return (
                                    <>
                                        <ProfilePicture
                                            name={created_by.first_name}
                                            email={created_by.email}
                                            size="md"
                                            showName
                                        />
                                    </>
                                )
                            }
                        },
                    },
                    {
                        width: 0,
                        render: function Render(_, exportRun: BatchExportRunType) {
                            return (
                                <More
                                    overlay={
                                        <div>
                                            {(exportRun.status === BatchExportStatus.Running ||
                                                exportRun.status === BatchExportStatus.Starting) && (
                                                <LemonButton
                                                    status="stealth"
                                                    fullWidth
                                                    onClick={() => {
                                                        changeExportRunStatus({
                                                            id: exportRun.id,
                                                            action: ChangeExportRunStatusEnum.Pause,
                                                        })
                                                    }}
                                                >
                                                    Pause
                                                </LemonButton>
                                            )}
                                            {exportRun.status === BatchExportStatus.Paused && (
                                                <LemonButton
                                                    status="stealth"
                                                    fullWidth
                                                    onClick={() => {
                                                        changeExportRunStatus({
                                                            id: exportRun.id,
                                                            action: ChangeExportRunStatusEnum.Resume,
                                                        })
                                                    }}
                                                >
                                                    Resume
                                                </LemonButton>
                                            )}
                                            <LemonButton
                                                status="danger"
                                                fullWidth
                                                onClick={() => {
                                                    if (exportRun.status === BatchExportStatus.Running) {
                                                        LemonDialog.open({
                                                            title: `Restart run created at ${exportRun.created_at}`,
                                                            description:
                                                                'This will cancel the existing run. This action cannot be undone.',
                                                            primaryButton: {
                                                                status: 'danger',
                                                                children: 'Restart',
                                                                onClick: () => {
                                                                    changeExportRunStatus({
                                                                        id: exportRun.id,
                                                                        action: ChangeExportRunStatusEnum.Restart,
                                                                    })
                                                                },
                                                            },
                                                        })
                                                    }
                                                }}
                                            >
                                                Restart
                                            </LemonButton>
                                            <LemonDivider />
                                            <LemonButton
                                                type="primary"
                                                status="danger"
                                                fullWidth
                                                onClick={() => {
                                                    LemonDialog.open({
                                                        title: `Delete run created at ${exportRun.created_at}`,
                                                        description: 'This action cannot be undone.',
                                                        primaryButton: {
                                                            status: 'danger',
                                                            children: 'Delete',
                                                            onClick: () => {
                                                                changeExportRunStatus({
                                                                    id: exportRun.id,
                                                                    action: ChangeExportRunStatusEnum.Delete,
                                                                })
                                                            },
                                                        },
                                                    })
                                                }}
                                            >
                                                Delete
                                            </LemonButton>
                                        </div>
                                    }
                                />
                            )
                        },
                    },
                ]}
                expandable={{
                    expandedRowRender: function Render(exportRun: BatchExportRunType) {
                        console.log(exportRun)
                        // TODO: change the above to use HistoricalExport
                        return <ExportRun exportRun={exportRun} />
                    },
                }}
                useURLForSorting={false}
                noSortingCancellation
                emptyState={
                    <div className="">
                        <b>Nothing has been exported yet!</b>
                        {
                            <p className="m-0">
                                Use "Start manual export" or create a schedule within "Settings" to export your data to
                                a destination.
                            </p>
                        }
                    </div>
                }
            />

            {/* {interfaceJobsProps && <PluginJobModal {...interfaceJobsProps} />} */}
        </div>
    )
}
