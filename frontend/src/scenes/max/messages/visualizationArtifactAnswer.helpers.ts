import { DataVisualizationNode, InsightVizNode } from '~/queries/schema/schema-general'
import { isInsightVizNode } from '~/queries/utils'
import { FilterLogicalOperator, RecordingUniversalFilters, UniversalFilterValue } from '~/types'

export function buildRecordingFiltersFromQuery(
    query: InsightVizNode | DataVisualizationNode
): Partial<RecordingUniversalFilters> | null {
    if (!isInsightVizNode(query)) {
        return null
    }
    const source = query.source
    if (!('series' in source) || !Array.isArray(source.series)) {
        return null
    }
    const filters: UniversalFilterValue[] = []
    source.series.forEach((series, index) => {
        if ('event' in series && series.event) {
            filters.push({
                id: series.event,
                name: series.event,
                type: 'events',
                order: index,
            } as UniversalFilterValue)
        }
    })
    if (filters.length === 0) {
        return null
    }
    return {
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [{ type: FilterLogicalOperator.And, values: filters }],
        },
        duration: [],
    }
}

export function deriveInsightName(query: InsightVizNode | DataVisualizationNode): string {
    if (isInsightVizNode(query) && 'series' in query.source) {
        const firstEvent = query.source.series.find((s) => 'event' in s && s.event)
        if (firstEvent && 'event' in firstEvent && firstEvent.event) {
            return `Max - ${firstEvent.event}`
        }
    }
    return 'Max-generated insight'
}
