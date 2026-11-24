import { dayjsNowInTimezone } from 'lib/dayjs'

import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, PropertyFilterType, PropertyOperator } from '~/types'

/** Daily count of all events that carry the property, over the same 30 days as the query usage card. */
export function propertyEventVolumeQuery(propertyName: string, timezone: string): TrendsQuery {
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
        // A fixed first day with explicitDate ends the range now, and ends the previous period at the same time of day
        // 30 days earlier. A relative range runs both periods to the end of their last day, so a partial today would
        // be compared with a whole day.
        dateRange: {
            date_from: dayjsNowInTimezone(timezone).subtract(29, 'day').format('YYYY-MM-DD'),
            explicitDate: true,
        },
        interval: 'day',
        compareFilter: { compare: true },
        filterTestAccounts: false,
    }
}
