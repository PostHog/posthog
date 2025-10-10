import { EventsNode, InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, PropertyFilterType, PropertyOperator } from '~/types'

import { SchemaPropertyGroupProperty } from '../schema/schemaManagementLogic'

export function buildPropertyGroupTrendsQuery(
    eventName: string,
    properties: SchemaPropertyGroupProperty[]
): InsightVizNode {
    const baseSeries: EventsNode = {
        kind: NodeKind.EventsNode,
        event: eventName,
        name: eventName,
        math: BaseMathType.TotalCount,
    }

    const series: EventsNode[] = [
        baseSeries,
        ...properties.map(
            (property): EventsNode => ({
                kind: NodeKind.EventsNode,
                event: eventName,
                name: eventName,
                properties: [
                    {
                        key: property.name,
                        type: PropertyFilterType.Event,
                        value: 'is_set',
                        operator: PropertyOperator.IsSet,
                    },
                ],
                math: BaseMathType.TotalCount,
            })
        ),
    ]

    const formulaNodes = properties.map((property, index) => {
        const seriesLetter = String.fromCharCode(66 + index)
        return {
            formula: `${seriesLetter}/A * 100`,
            custom_name: property.name,
        }
    })

    const trendsQuery: TrendsQuery = {
        kind: NodeKind.TrendsQuery,
        series,
        version: 2,
        interval: 'week',
        dateRange: {
            date_to: null,
            date_from: '-90d',
            explicitDate: false,
        },
        trendsFilter: {
            formulaNodes,
            showLegend: true,
            aggregationAxisFormat: 'percentage',
        },
    }

    return {
        kind: NodeKind.InsightVizNode,
        source: trendsQuery,
        showHeader: false,
        showTable: false,
        showFilters: false,
        embedded: true,
    }
}
