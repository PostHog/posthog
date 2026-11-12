import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, PropertyFilterType, PropertyOperator } from '~/types'

/** Daily count of all events that carry the property, over the same 30 days as the query usage card. */
export function propertyEventVolumeQuery(propertyName: string): TrendsQuery {
    return {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: null, name: 'All events', math: BaseMathType.TotalCount }],
        properties: [
            {
                key: propertyName,
                type: PropertyFilterType.Event,
                value: 'is_set',
                operator: PropertyOperator.IsSet,
            },
        ],
        dateRange: { date_from: '-29d' },
        interval: 'day',
        compareFilter: { compare: true },
        filterTestAccounts: false,
    }
}
