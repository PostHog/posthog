import { EventsNode, NodeKind } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

/** Convert an event name (or full URL) into an EventsNode for use in funnel series.
 *  URLs are detected and converted to $pageview events with a $current_url property filter. */
export function eventNameToEventsNode(eventName: string): EventsNode {
    const isPageview = /^https?:\/\//.test(eventName)
    return {
        kind: NodeKind.EventsNode,
        event: isPageview ? '$pageview' : eventName,
        name: isPageview ? '$pageview' : eventName,
        ...(isPageview && {
            properties: [
                {
                    key: '$current_url',
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                    value: eventName,
                },
            ],
        }),
    }
}
