import { Card } from 'antd'
import { useValues } from 'kea'
import React from 'react'
import { humanFriendlyDuration } from 'lib/utils'
import { AppMetricsGraph } from './AppMetricsGraph'
import { AppMetricsTab } from './appMetricsSceneLogic'
import { historicalExportLogic, HistoricalExportLogicProps } from './historicalExportLogic'
import { MetricsOverview } from './MetricsTab'
import { LemonSkeleton } from '../../lib/components/LemonSkeleton'

export function HistoricalExport(props: HistoricalExportLogicProps): JSX.Element {
    const { data, dataLoading } = useValues(historicalExportLogic(props))

    return (
        <div className="mt-4 mb-4 mr-8">
            <Card title="Overview">
                {dataLoading ? (
                    <LemonSkeleton className="h-12" />
                ) : (
                    <>
                        {data && data.summary.duration ? (
                            <div>
                                <div className="card-secondary">Export duration</div>
                                <div>{humanFriendlyDuration(data.summary.duration)}</div>
                            </div>
                        ) : null}
                        <MetricsOverview
                            tab={AppMetricsTab.HistoricalExports}
                            metrics={data?.metrics ?? null}
                            metricsLoading={dataLoading}
                        />
                    </>
                )}
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
