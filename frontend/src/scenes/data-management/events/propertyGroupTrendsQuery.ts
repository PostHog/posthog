import { EventsNode, InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, PropertyFilterType, PropertyOperator } from '~/types'

import { SchemaPropertyGroupProperty } from '../schema/schemaManagementLogic'

const MAX_PROPERTIES = 25

export interface PropertyGroupTrendsQueryResult {
    query: InsightVizNode
    isTruncated: boolean
    totalProperties: number
    displayedProperties: number
}

export function buildPropertyGroupTrendsQuery(
    eventName: string,
    properties: SchemaPropertyGroupProperty[]
): PropertyGroupTrendsQueryResult {
    // Limit to 25 properties since we use letters B-Z for series labels (A is reserved for the base series)
    const isTruncated = properties.length > MAX_PROPERTIES
    const limitedProperties = isTruncated ? properties.slice(0, MAX_PROPERTIES) : properties

    const baseSeries: EventsNode = {
        kind: NodeKind.EventsNode,
        event: eventName,
        name: eventName,
        math: BaseMathType.TotalCount,
    }

    const series: EventsNode[] = [
        baseSeries,
        ...limitedProperties.map(
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

    const formulaNodes = limitedProperties.map((property, index) => {
        // Generate series labels B, C, D, ... Z (ASCII 66 = 'B', 67 = 'C', etc.)
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
        query: {
            kind: NodeKind.InsightVizNode,
            source: trendsQuery,
            showHeader: false,
            showTable: false,
            showFilters: false,
            embedded: true,
        },
        isTruncated,
        totalProperties: properties.length,
        displayedProperties: limitedProperties.length,
    }
}
