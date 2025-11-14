import { ActionsNode, EventsNode } from '../../../frontend/src/queries/schema'

export interface CustomerAnalyticsEventsConfig {
    /**
     * @default null
     */
    activity_event: (EventsNode | ActionsNode) | null
}
