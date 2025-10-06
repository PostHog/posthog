import { InsightActorsQuery, NodeKind } from '~/queries/schema/schema-general'
import { GraphDataset } from '~/types'

interface DatasetToActorsQueryProps {
    dataset: GraphDataset
    query: InsightActorsQuery['source']
    day?: string | number
    index?: number
}

export function datasetToActorsQuery({ query, dataset, day, index }: DatasetToActorsQueryProps): InsightActorsQuery {
    const breakdown =
        dataset.breakdown_value ??
        (index !== undefined && Array.isArray(dataset.breakdownValues) ? dataset.breakdownValues[index] : undefined)
    const compare =
        (dataset.compare_label ??
            (index !== undefined && Array.isArray(dataset.compareLabels) ? dataset.compareLabels[index] : undefined)) ||
        undefined
    return {
        kind: NodeKind.InsightActorsQuery,
        source: query,
        day,
        status: dataset.status,
        series: dataset.action?.order ?? 0,
        breakdown,
        compare,
        includeRecordings: true,
    }
}
