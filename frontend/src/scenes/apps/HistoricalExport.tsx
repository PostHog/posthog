import { useValues } from 'kea'
import React from 'react'
import { AppMetricsTab } from './appMetricsSceneLogic'
import { historicalExportLogic, HistoricalExportLogicProps } from './historicalExportLogic'
import { MetricsTab } from './MetricsTab'

export function HistoricalExport(props: HistoricalExportLogicProps): JSX.Element {
    const { data, dataLoading } = useValues(historicalExportLogic(props))

    return (
        <MetricsTab
            tab={AppMetricsTab.HistoricalExports}
            metrics={data?.metrics ?? null}
            metricsLoading={dataLoading}
        />
    )
}
