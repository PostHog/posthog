import { Message } from 'node-rdkafka'

import { Team } from '../types'

/**
 * Common types and utilities shared across ingestion pipelines
 */

/**
 * Base input type for event processing pipelines that includes the essential context
 * needed to process an event after preprocessing.
 */
export interface EventProcessingPipelineInput {
    message: Message
    event: any
    team: Team
    headers: any
    personsStoreForBatch: any
    groupStoreForBatch: any
}

/**
 * Determines which pipeline branch an event should be routed to based on its event name.
 * This is the routing logic that splits incoming events into different processing paths.
 */
export function routeEventToPipeline(event: any): 'client_ingestion_warning' | 'heatmap' | 'analytics' {
    switch (event.event) {
        case '$$client_ingestion_warning':
            return 'client_ingestion_warning'
        case '$$heatmap':
            return 'heatmap'
        default:
            return 'analytics'
    }
}

/**
 * Type guard to check if an event is a client ingestion warning event
 */
export function isClientIngestionWarningEvent(event: any): boolean {
    return event.event === '$$client_ingestion_warning'
}

/**
 * Type guard to check if an event is a heatmap event
 */
export function isHeatmapEvent(event: any): boolean {
    return event.event === '$$heatmap'
}

/**
 * Type guard to check if an event is a regular analytics event
 */
export function isAnalyticsEvent(event: any): boolean {
    return !isClientIngestionWarningEvent(event) && !isHeatmapEvent(event)
}
