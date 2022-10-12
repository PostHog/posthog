import { Card } from 'antd'
import { useValues } from 'kea'
import React from 'react'
import { AppMetricsGraph } from './AppMetricsGraph'
import { AppMetricsTab } from './appMetricsSceneLogic'
import { historicalExportLogic, HistoricalExportLogicProps } from './historicalExportLogic'
import { MetricsOverview } from './MetricsTab'

export function HistoricalExport(props: HistoricalExportLogicProps): JSX.Element {
    const { data, dataLoading } = useValues(historicalExportLogic(props))

    return (
        <div className="mt-4 mb-4 mr-8">
            <Card title="Overview">
                <MetricsOverview
                    tab={AppMetricsTab.HistoricalExports}
                    metrics={data?.metrics ?? null}
                    metricsLoading={dataLoading}
                />
            </Card>

            <Card title="Delivery trends" className="mt-4">
                <AppMetricsGraph
                    tab={AppMetricsTab.HistoricalExports}
                    metrics={data?.metrics ?? null}
                    metricsLoading={dataLoading}
                />
            </Card>
        </div>
    )
}
