import { useValues } from 'kea'
import React from 'react'
import { historicalExportLogic, HistoricalExportLogicProps } from './historicalExportLogic'
import { MetricsTab } from './MetricsTab'

export function HistoricalExport(props: HistoricalExportLogicProps): JSX.Element {
    const { data, dataLoading } = useValues(historicalExportLogic(props))

    if (!data || dataLoading) {
        return <></>
    }

    return <MetricsTab metrics={data.metrics} metricsLoading={dataLoading} />
}
