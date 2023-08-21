import { useActions, useValues } from 'kea'
import { appMetricsSceneLogic, HistoricalExportInfo } from './appMetricsSceneLogic'
import { LemonTable, LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { HistoricalExport } from './HistoricalExport'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Progress } from 'antd'
import { PluginJobModal } from 'scenes/plugins/edit/interface-jobs/PluginJobConfiguration'
import { useEffect } from 'react'
import { LemonButton } from 'lib/lemon-ui/LemonButton/LemonButton'
import { userLogic } from 'scenes/userLogic'

const RELOAD_HISTORICAL_EXPORTS_FREQUENCY_MS = 20000

export function HistoricalExportsTab(): JSX.Element {
    const { historicalExports, historicalExportsLoading, pluginConfig, interfaceJobsProps, hasRunningExports } =
        useValues(appMetricsSceneLogic)
    const { openHistoricalExportModal, loadHistoricalExports } = useActions(appMetricsSceneLogic)
    const { user } = useValues(userLogic)

    useEffect(() => {
        let timer: NodeJS.Timeout | undefined

        function updateTimer(): void {
            if (hasRunningExports) {
                timer = setTimeout(() => {
                    loadHistoricalExports()
                    updateTimer()
                }, RELOAD_HISTORICAL_EXPORTS_FREQUENCY_MS)
            }
        }

        updateTimer()
        return () => timer && clearTimeout(timer)
    }, [hasRunningExports])

    return (
        <div className="space-y-2">
            {user?.is_impersonated && (
                <div className="flex items-center justify-end">
                    <LemonButton type="primary" onClick={openHistoricalExportModal} disabled={!interfaceJobsProps}>
                        Start new export
                    </LemonButton>
                </div>
            )}
            <LemonTable
                dataSource={historicalExports}
                loading={historicalExportsLoading}
                columns={[
                    {
                        title: 'Dates exported',
                        render: function Render(_, historicalExport: HistoricalExportInfo) {
                            const [dateFrom, dateTo] = historicalExport.payload.dateRange
                            if (dateFrom === dateTo) {
                                return dateFrom
                            }
                            return `${dateFrom} - ${dateTo}`
                        },
                    },
                    {
                        title: 'Progress',
                        width: 130,
                        render: function RenderProgress(_, historicalExport: HistoricalExportInfo) {
                            switch (historicalExport.status) {
                                case 'success':
                                    return (
                                        <LemonTag type="success" className="uppercase">
                                            Success
                                        </LemonTag>
                                    )
                                case 'fail':
                                    return (
                                        <LemonTag type="danger" className="uppercase">
                                            Failed
                                        </LemonTag>
                                    )
                                case 'not_finished':
                                    return <Progress percent={Math.floor((historicalExport.progress || 0) * 100)} />
                            }
                        },
                        align: 'right',
                    },
                    createdByColumn() as LemonTableColumn<HistoricalExportInfo, any>,
                    createdAtColumn() as LemonTableColumn<HistoricalExportInfo, any>,
                ]}
                expandable={{
                    expandedRowRender: function Render(historicalExport: HistoricalExportInfo) {
                        if (!pluginConfig) {
                            return
                        }
                        return <HistoricalExport pluginConfigId={pluginConfig.id} jobId={historicalExport.job_id} />
                    },
                }}
                useURLForSorting={false}
                noSortingCancellation
                emptyState={
                    <div className="">
                        <b>Nothing has been exported yet!</b>
                    </div>
                }
            />

            {interfaceJobsProps && <PluginJobModal {...interfaceJobsProps} />}
        </div>
    )
}
