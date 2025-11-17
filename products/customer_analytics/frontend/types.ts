import { ActionsNode, EventsNode } from '../../../frontend/src/queries/schema'

export interface CustomerAnalyticsEventsConfig {
    /**
     * @default null
     */
    activity_event: (EventsNode | ActionsNode) | null
}

export interface CustomerAnalyticsConfigType {
    id: string
    activity_event: (EventsNode | ActionsNode) | null
}
