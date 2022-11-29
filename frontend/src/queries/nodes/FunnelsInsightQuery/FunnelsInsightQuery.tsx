import { EventsNode, ActionsNode, FunnelsQuery } from '~/queries/schema'
import { InsightLogicProps, FilterType, InsightType, ActionFilter } from '~/types'
import { isEventsNode } from '~/queries/utils'
import { BindLogic } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { AdHocInsight } from 'lib/components/AdHocInsight/AdHocInsight'

const seriesToActionsAndEvents = (
    series: (EventsNode | ActionsNode)[]
): { events: ActionFilter[]; actions: ActionFilter[] } => {
    const actions: ActionFilter[] = []
    const events: ActionFilter[] = []
    series.forEach((node, index) => {
        const entity: ActionFilter = {
            type: isEventsNode(node) ? 'events' : 'actions',
            id: (isEventsNode(node) ? node.event : node.id) || null,
            order: index,
            name: node.name || null,
            custom_name: node.custom_name,
            math: node.math,
            math_property: node.math_property,
            math_group_type_index: node.math_group_type_index,
            properties: node.properties as any, // TODO,
        }

        if (isEventsNode(node)) {
            events.push(entity)
        } else {
            actions.push(entity)
        }
    })
    return { actions, events }
}

const filtersFromTrendsQuery = (query: FunnelsQuery): Partial<FilterType> => {
    return {
        insight: InsightType.FUNNELS,
        interval: query.interval,
        ...query.dateRange,
        ...seriesToActionsAndEvents(query.series),
        properties: query.properties,
        filter_test_accounts: query.filterTestAccounts,
        ...query.funnelsFilter,
        ...query.breakdown,
    }
}

/** Use new FunnelsQuery and transform it into old insight props to display the funnels graph. */
export function FunnelsInsightQuery({ query }: { query: FunnelsQuery }): JSX.Element {
    const filters: Partial<FilterType> = filtersFromTrendsQuery(query)
    const insightProps: InsightLogicProps = { dashboardItemId: 'new', cachedInsight: { filters } }

    return (
        <BindLogic logic={insightLogic} props={insightProps} key={JSON.stringify(filters)}>
            <AdHocInsight filters={filters} style={{ height: 500, border: '1px var(--primary) solid' }} />
        </BindLogic>
    )
}
