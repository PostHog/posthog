import { EventsNode, isEventsNode, isLegacyQuery, isSavedInsight, LegacyQuery, Node, SavedInsightNode } from './nodes'
import { BindLogic } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { AnyPropertyFilter, InsightLogicProps, ItemMode } from '~/types'
import { InsightContainer } from 'scenes/insights/InsightContainer'
import { EventsTable } from 'scenes/events'
import { useState } from 'react'

export interface PostHogQueryProps {
    query: Node
}
export function PostHogQuery({ query }: PostHogQueryProps): JSX.Element {
    if (isLegacyQuery(query)) {
        return <LegacyInsightQuery query={query} />
    } else if (isSavedInsight(query)) {
        return <SavedInsightQuery query={query} />
    } else if (isEventsNode(query)) {
        return <EventsNodeQuery query={query} />
    }

    return (
        <div className="text-danger border border-danger p-2">
            <strong>PostHoqQuery error:</strong>{' '}
            {query?.nodeType ? `Invalid node type "${query.nodeType}"` : 'Invalid query'}
        </div>
    )
}

export function LegacyInsightQuery({ query }: { query: LegacyQuery }): JSX.Element {
    const insightProps: InsightLogicProps = { dashboardItemId: 'new', cachedInsight: { filters: query.filters } }
    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <InsightContainer insightMode={ItemMode.View} disableHeader disableTable disableCorrelationTable />
        </BindLogic>
    )
}

export function SavedInsightQuery({ query }: { query: SavedInsightNode }): JSX.Element {
    const insightProps: InsightLogicProps = { dashboardItemId: query.shortId }
    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <InsightContainer insightMode={ItemMode.View} disableHeader disableTable disableCorrelationTable />
        </BindLogic>
    )
}

let uniqueNode = 0
export function EventsNodeQuery({ query }: { query: EventsNode }): JSX.Element {
    const [id] = useState(uniqueNode++)

    return (
        <EventsTable
            pageKey={`events-node-${id}`}
            fixedFilters={{ properties: query.properties as AnyPropertyFilter[] }}
        />
    )
}
