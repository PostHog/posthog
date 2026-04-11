import { DateDisplay } from 'lib/components/DateDisplay'

import { InsightActorsQuery, InsightVizNode, ResolvedDateRangeResponse } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { IntervalType } from '~/types'

import type { OpenPersonsModalProps } from '../persons-modal/PersonsModal'
import type { IndexedTrendResult } from '../types'
import { datasetToActorsQuery } from './datasetToActorsQuery'

export interface TrendsLineChartClickDeps {
    context?: QueryContext<InsightVizNode>
    hasPersonsModal: boolean
    interval: IntervalType | null | undefined
    timezone: string
    weekStartDay: number | null | undefined
    resolvedDateRange: ResolvedDateRangeResponse | null | undefined
    querySource: InsightActorsQuery['source'] | null | undefined
    indexedResults: IndexedTrendResult[]
    // Injected so the adapter stays decoupled from PersonsModal's dep graph.
    openPersonsModal: (props: OpenPersonsModalProps) => void
}

// TrendsLineChartD3 keys each hog-charts Series by `${r.id}`, so we can
// resolve back to the source IndexedTrendResult without stashing it on meta.
function resolveDataset(seriesKey: string, indexedResults: IndexedTrendResult[]): IndexedTrendResult | null {
    return indexedResults.find((r) => String(r.id) === seriesKey) ?? null
}

export function handleTrendsLineChartClick(seriesKey: string, dataIndex: number, deps: TrendsLineChartClickDeps): void {
    const dataset = resolveDataset(seriesKey, deps.indexedResults)
    if (!dataset) {
        return
    }

    const day = dataset.action?.days?.[dataIndex] ?? dataset.days?.[dataIndex]
    if (day == null || day === '') {
        return
    }

    if (deps.context?.onDataPointClick) {
        deps.context.onDataPointClick(
            {
                breakdown: dataset.breakdown_value,
                compare: dataset.compare_label || undefined,
                day,
            },
            // Legacy parity with ActionsLineGraph — passes the first result, not the clicked one.
            deps.indexedResults[0]
        )
        return
    }

    if (!deps.hasPersonsModal || !deps.querySource) {
        return
    }

    const title = (actorLabel: string): JSX.Element => (
        <>
            {actorLabel} on{' '}
            <DateDisplay
                interval={deps.interval || 'day'}
                resolvedDateRange={deps.resolvedDateRange ?? undefined}
                timezone={deps.timezone}
                weekStartDay={deps.weekStartDay ?? undefined}
                date={day}
            />
        </>
    )

    deps.openPersonsModal({
        title,
        query: datasetToActorsQuery({ dataset, query: deps.querySource, day }),
        additionalSelect: {
            value_at_data_point: 'event_count',
            matched_recordings: 'matched_recordings',
        },
        orderBy: ['event_count DESC, actor_id DESC'],
    })
}
