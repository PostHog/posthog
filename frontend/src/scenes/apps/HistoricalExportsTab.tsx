import React from 'react'
import { useValues } from 'kea'
import { appMetricsSceneLogic, HistoricalExportInfo } from './appMetricsSceneLogic'
import { LemonTable, LemonTableColumn } from 'lib/components/LemonTable'
import { HistoricalExport } from './HistoricalExport'
import { createdAtColumn, createdByColumn } from 'lib/components/LemonTable/columnUtils'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'

export function HistoricalExportsTab(): JSX.Element {
    const { historicalExports, historicalExportsLoading, pluginConfig } = useValues(appMetricsSceneLogic)

    return (
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
                    title: 'Status',
                    width: 100,
                    render: function RenderActive(_, historicalExport: HistoricalExportInfo) {
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
                                return (
                                    <LemonTag type="default" className="uppercase">
                                        Running
                                    </LemonTag>
                                )
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
        />
    )
}
