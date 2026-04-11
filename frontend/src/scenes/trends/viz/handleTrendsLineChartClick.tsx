import { DateDisplay } from 'lib/components/DateDisplay'

import { InsightVizNode, ResolvedDateRangeResponse, TrendsQuery } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { GraphDataset, IntervalType } from '~/types'

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
    querySource: TrendsQuery | null | undefined
    indexedResults: IndexedTrendResult[]
    // Injected so the adapter stays decoupled from PersonsModal's dep graph.
    openPersonsModal: (props: OpenPersonsModalProps) => void
}

// TrendsLineChartD3 keys each hog-charts Series by `${r.id}`, so we can
// resolve back to the source IndexedTrendResult without stashing it on meta.
function resolveDataset(seriesKey: string, indexedResults: IndexedTrendResult[]): GraphDataset | null {
    const match = indexedResults.find((r) => String(r.id) === seriesKey)
    return (match as GraphDataset | undefined) ?? null
}

export function handleTrendsLineChartClick(seriesKey: string, dataIndex: number, deps: TrendsLineChartClickDeps): void {
    const dataset = resolveDataset(seriesKey, deps.indexedResults)
    if (!dataset) {
        return
    }

    const day = dataset.action?.days?.[dataIndex] ?? dataset.days?.[dataIndex] ?? ''

    if (deps.context?.onDataPointClick) {
        deps.context.onDataPointClick(
            {
                breakdown: dataset.breakdownValues?.[dataIndex],
                compare: dataset.compareLabels?.[dataIndex] || undefined,
                day,
            },
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
                date={day?.toString() || ''}
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
