import { dayjs } from 'lib/dayjs'

import { EventsNode, InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, PropertyFilterType, PropertyOperator } from '~/types'

import { SchemaPropertyGroupProperty } from '../schema/schemaManagementLogic'

const MAX_PROPERTIES = 25
const LOOKBACK_DAYS = 90

export interface PropertyGroupTrendsQueryResult {
    query: InsightVizNode
    isTruncated: boolean
    totalProperties: number
    displayedProperties: number
    /** Human-readable description of the charted window, e.g. "last 90 days" or "since Jun 15, 2026". */
    dateRangeLabel: string
}

export function buildPropertyGroupTrendsQuery(
    eventName: string,
    properties: SchemaPropertyGroupProperty[],
    eventFirstSeen?: string | null
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

    // Coverage is `propertyCount / eventCount`, so weeks where the event never fired evaluate to 0/0,
    // which the formula engine renders as 0% rather than a gap. For an event younger than the lookback
    // window that paints a misleading flat 0% line across every week before the event existed, hiding
    // the real coverage in the final buckets. Never start the window before the event first appeared.
    const defaultFrom = dayjs().subtract(LOOKBACK_DAYS, 'day')
    const firstSeen = eventFirstSeen ? dayjs(eventFirstSeen) : null
    const clampedFrom = firstSeen && firstSeen.isValid() && firstSeen.isAfter(defaultFrom) ? firstSeen : null
    const dateFrom = clampedFrom ? clampedFrom.format('YYYY-MM-DD') : `-${LOOKBACK_DAYS}d`
    const dateRangeLabel = clampedFrom ? `since ${clampedFrom.format('MMM D, YYYY')}` : `last ${LOOKBACK_DAYS} days`

    const trendsQuery: TrendsQuery = {
        kind: NodeKind.TrendsQuery,
        series,
        version: 2,
        interval: 'week',
        dateRange: {
            date_to: null,
            date_from: dateFrom,
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
        dateRangeLabel,
    }
}
