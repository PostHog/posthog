import { MetricsWidgetChart } from 'products/metrics/frontend/widgets/MetricsWidgetChart'

import type { MetricsWidgetPresetId } from '../metrics/metricsWidgetConfig'
import { metricsWidgetSampleQuery, metricsWidgetSampleResponse } from '../metrics/metricsWidgetSampleData'

export function MetricsWidgetPreview({ presetId }: { presetId?: string }): JSX.Element {
    const preset = (presetId ?? 'time_series') as MetricsWidgetPresetId
    return (
        <div className="flex h-36 flex-col" translate="no">
            <MetricsWidgetChart
                query={metricsWidgetSampleQuery(preset)}
                response={metricsWidgetSampleResponse(preset)}
            />
        </div>
    )
}
