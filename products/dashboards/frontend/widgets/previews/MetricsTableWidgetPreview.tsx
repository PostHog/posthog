import { MetricsTableView } from '../metrics/MetricsTableWidget'
import { metricsTableWidgetSampleResult } from '../metrics/metricsTableWidgetSampleData'

export function MetricsTableWidgetPreview(): JSX.Element {
    return (
        <div className="shadow-sm">
            <MetricsTableView
                groupBy={metricsTableWidgetSampleResult.groupBy ?? ''}
                columns={metricsTableWidgetSampleResult.columns ?? []}
                rows={(metricsTableWidgetSampleResult.rows ?? []).slice(0, 4)}
            />
        </div>
    )
}
