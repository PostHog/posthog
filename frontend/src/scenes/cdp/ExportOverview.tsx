import { useValues } from 'kea'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ExportRunType } from './types'
import { NewConnectionLogic } from './NewConnectionLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

export function ExportOverviewTab(): JSX.Element {
    const { exportRuns, exportRunsLoading } = useValues(NewConnectionLogic)
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
                    Re-run all failed jobs
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
                                    <TZLabel time={created_at} />
                                </div>
                            ) : (
                                <span className="text-muted">—</span>
                            )
                        },
                        sorter: (a, b) => (new Date(a.created_at || 0) > new Date(b.created_at || 0) ? 1 : -1),
                    },
                    {
                        title: 'Event count',
                        render: function Render(_, exportRun: ExportRunType) {
                            return exportRun.row_count
                        },
                    },
                    {
                        title: 'Event range',
                        render: function Render(_, exportRun: ExportRunType) {
                            return exportRun.filters
                        },
                    },
                    {
                        title: 'Status',
                        render: function Render(_, exportRun: ExportRunType) {
                            return <LemonTag>{exportRun.status}</LemonTag>
                        },
                    },
                    {
                        title: 'Created by',
                        render: function Render(_: any, exportRun: ExportRunType) {
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
                    // {
                    //     title: 'Progress',
                    //     width: 130,
                    //     render: function RenderProgress(_, historicalExport: HistoricalExportInfo) {
                    //         switch (historicalExport.status) {
                    //             case 'success':
                    //                 return (
                    //                     <LemonTag type="success" className="uppercase">
                    //                         Success
                    //                     </LemonTag>
                    //                 )
                    //             case 'fail':
                    //                 return (
                    //                     <LemonTag type="danger" className="uppercase">
                    //                         Failed
                    //                     </LemonTag>
                    //                 )
                    //             case 'not_finished':
                    //                 return <Progress percent={Math.floor((historicalExport.progress || 0) * 100)} />
                    //         }
                    //     },
                    //     align: 'right',
                    // },
                    // createdAtColumn() as LemonTableColumn<HistoricalExportInfo, any>,
                ]}
                // expandable={{
                //     expandedRowRender: function Render(historicalExport: HistoricalExportInfo) {
                //         if (!pluginConfig) {
                //             return
                //         }
                //         return <HistoricalExport pluginConfigId={pluginConfig.id} jobId={historicalExport.job_id} />
                //     },
                // }}
                useURLForSorting={false}
                noSortingCancellation
                emptyState={
                    <div className="">
                        <b>Nothing has been exported yet!</b>
                        {/* {interfaceJobsProps && (
                            <p className="m-0">
                                Use "Start new export" button above to export historical data in a given time range.
                            </p>
                        )} */}
                    </div>
                }
            />

            {/* {interfaceJobsProps && <PluginJobModal {...interfaceJobsProps} />} */}
        </div>
    )
}
