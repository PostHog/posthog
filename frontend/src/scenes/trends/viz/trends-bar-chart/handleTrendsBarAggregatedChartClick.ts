import { datasetToActorsQuery } from '../datasetToActorsQuery'
import type { TrendsChartClickDeps } from '../handleTrendsChartClick'

// Sparse-stacked: resolve by dataIndex, not series.key — buildPointClickData would otherwise
// dispatch the first non-excluded series regardless of which band was clicked.
export function handleTrendsBarAggregatedChartClick(dataIndex: number, deps: TrendsChartClickDeps): void {
    const dataset = deps.indexedResults[dataIndex]
    if (!dataset) {
        return
    }

    if (deps.context?.onDataPointClick) {
        deps.context.onDataPointClick(
            {
                breakdown: dataset.breakdown_value,
                compare: dataset.compare_label || undefined,
            },
            // Legacy parity with ActionsHorizontalBar — passes the first result, not the clicked one.
            deps.indexedResults[0]
        )
        return
    }

    if (!deps.hasPersonsModal || !deps.querySource) {
        return
    }

    deps.openPersonsModal({
        title: dataset.label || '',
        query: datasetToActorsQuery({ dataset, query: deps.querySource }),
        additionalSelect: {
            value_at_data_point: 'event_count',
            matched_recordings: 'matched_recordings',
        },
        orderBy: ['event_count DESC, actor_id DESC'],
    })
}
