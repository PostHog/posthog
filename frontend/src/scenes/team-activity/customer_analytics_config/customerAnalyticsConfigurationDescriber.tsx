import { ActivityChange, ChangeMapping } from 'lib/components/ActivityLog/humanizeActivity'

import { ActionsNode, CustomerAnalyticsConfig, EventsNode, NodeKind } from '~/queries/schema/schema-general'

import { ConfigurationAddedDescriber } from './ConfigurationAddedDescriber'
import { ConfigurationRemovedDescriber } from './ConfigurationRemovedDescriber'
import { EventAddedDescriber } from './EventAddedDescriber'
import { EventChangedDescriber } from './EventChangedDescriber'
import { EventRemovedDescriber } from './EventRemovedDescriber'

export const customerAnalyticsConfigurationDescriber = (change?: ActivityChange): ChangeMapping | null => {
    if (!change) {
        return null
    }

    const before = (change.before ?? {}) as CustomerAnalyticsConfig
    const after = (change.after ?? {}) as CustomerAnalyticsConfig

    const eventConfigDescriptions = customerAnalyticsEventConfigDescriber(before, after) ?? []

    return { description: [...eventConfigDescriptions] }
}

type EventType = 'activity_event' | 'signup_pageview_event' | 'signup_event' | 'subscription_event' | 'payment_event'

const EVENT_TYPE_LABELS: Record<EventType, string> = {
    activity_event: 'Activity event',
    signup_pageview_event: 'Signup pageview event',
    signup_event: 'Signup event',
    subscription_event: 'Subscription event',
    payment_event: 'Payment event',
}

function isValidEventConfig(config: any): config is EventsNode | ActionsNode {
    return (
        config &&
        typeof config === 'object' &&
        'kind' in config &&
        (config.kind === NodeKind.EventsNode || config.kind === NodeKind.ActionsNode)
    )
}

const customerAnalyticsEventConfigDescriber = (
    before: CustomerAnalyticsConfig,
    after: CustomerAnalyticsConfig
): JSX.Element[] | null => {
    const descriptions: JSX.Element[] = []

    const eventTypes: EventType[] = [
        'activity_event',
        'signup_pageview_event',
        'signup_event',
        'subscription_event',
        'payment_event',
    ]

    const hasAnyBefore = eventTypes.some((type) => isValidEventConfig(before[type]))
    const hasAnyAfter = eventTypes.some((type) => isValidEventConfig(after[type]))

    if (!hasAnyBefore && hasAnyAfter) {
        // First configuration ever
        const firstConfiguredType = eventTypes.find((type) => isValidEventConfig(after[type]))
        if (firstConfiguredType) {
            descriptions.push(
                <ConfigurationAddedDescriber
                    eventType={EVENT_TYPE_LABELS[firstConfiguredType]}
                    eventConfig={after[firstConfiguredType]}
                />
            )
        }
    } else if (hasAnyBefore && !hasAnyAfter) {
        // All configurations removed
        const lastRemovedType = eventTypes.find((type) => isValidEventConfig(before[type]))
        if (lastRemovedType) {
            descriptions.push(
                <ConfigurationRemovedDescriber
                    eventType={EVENT_TYPE_LABELS[lastRemovedType]}
                    eventConfig={before[lastRemovedType]}
                />
            )
        }
    } else {
        // Process individual field changes
        for (const eventType of eventTypes) {
            const beforeEvent = before[eventType] as EventsNode | ActionsNode | undefined
            const afterEvent = after[eventType] as EventsNode | ActionsNode | undefined

            const beforeValid = isValidEventConfig(beforeEvent)
            const afterValid = isValidEventConfig(afterEvent)

            if (!beforeValid && afterValid) {
                descriptions.push(
                    <EventAddedDescriber eventType={EVENT_TYPE_LABELS[eventType]} eventConfig={afterEvent} />
                )
            } else if (beforeValid && !afterValid) {
                descriptions.push(
                    <EventRemovedDescriber eventType={EVENT_TYPE_LABELS[eventType]} eventConfig={beforeEvent} />
                )
            } else if (beforeValid && afterValid && !areEventsEqual(beforeEvent, afterEvent)) {
                descriptions.push(
                    <EventChangedDescriber
                        eventType={EVENT_TYPE_LABELS[eventType]}
                        beforeConfig={beforeEvent}
                        afterConfig={afterEvent}
                    />
                )
            }
        }
    }

    return descriptions.length > 0 ? descriptions : null
}

function areEventsEqual(event1: EventsNode | ActionsNode, event2: EventsNode | ActionsNode): boolean {
    if (event1.kind !== event2.kind) {
        return false
    }

    if (event1.kind === NodeKind.EventsNode && event2.kind === NodeKind.EventsNode) {
        return event1.event === event2.event
    }

    if (event1.kind === NodeKind.ActionsNode && event2.kind === NodeKind.ActionsNode) {
        return event1.id === event2.id
    }

    return false
}
