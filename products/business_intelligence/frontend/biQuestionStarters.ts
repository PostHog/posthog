import { urls } from 'scenes/urls'

import { BIConfig, BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { buildBIQuery, DEFAULT_BI_CONFIG, getBIValueSortKey } from './biEditorTypes'

export function starterWorksheetUrl(config: BIConfig): string {
    const built = buildBIQuery(config)!
    const worksheet: BIVisualizationNode = { ...built.node, kind: NodeKind.BIVisualizationNode, config }
    return `${urls.businessIntelligenceNew()}?starter=1#q=${encodeURIComponent(JSON.stringify(worksheet))}`
}

export const EVENTS_CONFIG: BIConfig = {
    ...DEFAULT_BI_CONFIG,
    source: { table: 'events' },
    dateRange: { date_from: '-7d' },
    chartType: ChartDisplayType.ActionsLineGraph,
    rows: [
        {
            id: 'starter:timestamp',
            name: 'timestamp',
            expression: 'timestamp',
            source: { table: 'events' },
            type: 'datetime',
            dateBucket: 'day',
        },
    ],
}

const people = {
    field: {
        id: 'starter:person_id',
        name: 'person_id',
        expression: 'person_id',
        source: { table: 'events' },
        type: 'string' as const,
    },
    aggregation: 'count_distinct' as const,
    display: { label: 'People' },
}
const eventReach: BIConfig = {
    ...EVENTS_CONFIG,
    chartType: ChartDisplayType.ActionsBar,
    rows: [{ id: 'starter:event', name: 'event', expression: 'event', source: { table: 'events' }, type: 'string' }],
    values: [people],
    limit: 100,
}

export const BI_QUESTION_STARTERS = [
    {
        id: 'events' as const,
        title: 'How many events happen each day?',
        description: 'Daily event count · Last 7 days',
        config: EVENTS_CONFIG,
    },
    {
        id: 'daily_people' as const,
        title: 'How many people are active each day?',
        description: 'Distinct people per day · Last 7 days',
        config: { ...EVENTS_CONFIG, values: [people] },
    },
    {
        id: 'event_reach' as const,
        title: 'Which events reach the most people?',
        description: 'Events ranked by distinct people · Last 7 days',
        config: { ...eventReach, sort: { key: getBIValueSortKey(eventReach, 0)!, direction: 'desc' as const } },
    },
    {
        id: 'pageview_sources' as const,
        title: 'Where do page views come from?',
        description: 'Page views by referring domain · Last 7 days',
        config: {
            ...EVENTS_CONFIG,
            chartType: ChartDisplayType.ActionsBar,
            rows: [
                {
                    id: 'starter:referring_domain',
                    name: 'Referring domain',
                    expression: 'properties.$referring_domain',
                    source: { table: 'events' },
                    type: 'string' as const,
                },
            ],
            filters: [{ field: eventReach.rows[0], operator: 'equals' as const, value: '$pageview' }],
        },
    },
]
