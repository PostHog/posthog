import { useValues } from 'kea'

import { AppMetricsTab } from '~/types'

import { AppMetricsGraph } from './AppMetricsGraph'
import { historicalExportLogic, HistoricalExportLogicProps } from './historicalExportLogic'
import { ErrorsOverview, MetricsOverview } from './MetricsTab'

export function HistoricalExport(props: HistoricalExportLogicProps): JSX.Element {
    const { data, dataLoading } = useValues(historicalExportLogic(props))

    return (
        <div className="space-y-8">
            <MetricsOverview
                tab={AppMetricsTab.HistoricalExports}
                metrics={data?.metrics ?? null}
                metricsLoading={dataLoading}
                exportDuration={data?.summary?.duration}
                exportFailureReason={data?.summary?.failure_reason}
            />

            <div>
                <h2>Delivery trends</h2>
                <AppMetricsGraph
                    tab={AppMetricsTab.HistoricalExports}
                    metrics={data?.metrics ?? null}
                    metricsLoading={dataLoading}
                />
            </div>

            <div>
                <h2>Errors</h2>
                <ErrorsOverview
                    errors={data?.errors || []}
                    loading={dataLoading}
                    category="exportEvents"
                    jobId={data?.summary?.job_id}
                />
            </div>
        </div>
    )
}
