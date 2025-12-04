import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import {
    ActionsNode,
    EventsNode,
    InsightQueryNode,
    InsightVizNode,
    LifecycleQuery,
    NodeKind,
    RetentionQuery,
    StickinessQuery,
} from '~/queries/schema/schema-general'
import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import { EntityTypes, IntervalType, RetentionPeriod } from '~/types'

export type FollowUpSuggestion = {
    title: string
    description?: string
    targetQuery: InsightVizNode
}

/**
 * Get suggested follow-up insights for a given query.
 * Returns an array of suggestions that help users dive deeper into their data.
 */
export function getSuggestedFollowUps(query: InsightQueryNode): FollowUpSuggestion[] {
    if (query.kind === NodeKind.RetentionQuery) {
        return getRetentionFollowUps(query)
    }

    // Future: Add handlers for other insight types
    // if (query.kind === NodeKind.FunnelsQuery) { return getFunnelFollowUps(query) }
    // if (query.kind === NodeKind.TrendsQuery) { return getTrendsFollowUps(query) }

    return []
}

/**
 * Get follow-up suggestions for retention insights.
 * Currently suggests a stickiness insight for the return event.
 */
function getRetentionFollowUps(query: RetentionQuery): FollowUpSuggestion[] {
    const { retentionFilter } = query
    const returningEntity = retentionFilter?.returningEntity

    if (!returningEntity) {
        return []
    }

    // Build the series for stickiness based on the returning entity
    let series: (EventsNode | ActionsNode)[] = []
    let entityDisplayName = 'event'

    if (returningEntity.type === EntityTypes.EVENTS || returningEntity.kind === NodeKind.EventsNode) {
        const eventName = returningEntity.id || returningEntity.name || 'event'

        if (typeof eventName === 'string') {
            const coreDefinition = getCoreFilterDefinition(eventName, TaxonomicFilterGroupType.Events)
            entityDisplayName = coreDefinition?.label || eventName
        } else {
            entityDisplayName = 'event'
        }

        series = [
            {
                kind: NodeKind.EventsNode,
                event: typeof eventName === 'string' ? eventName : null,
                name: returningEntity.name,
                custom_name: returningEntity.custom_name,
                properties: returningEntity.properties,
            },
        ]
    } else if (returningEntity.type === EntityTypes.ACTIONS || returningEntity.kind === NodeKind.ActionsNode) {
        const actionId =
            typeof returningEntity.id === 'number'
                ? returningEntity.id
                : parseInt(String(returningEntity.id || '0'), 10)
        entityDisplayName = returningEntity.name || `Action ${actionId}`

        series = [
            {
                kind: NodeKind.ActionsNode,
                id: actionId,
                name: returningEntity.name,
                custom_name: returningEntity.custom_name,
                properties: returningEntity.properties,
            },
        ]
    } else {
        // Unknown entity type
        return []
    }

    // Auto-detect interval based on retention period
    const retentionPeriod = retentionFilter?.period ?? RetentionPeriod.Day
    let interval: IntervalType
    let intervalDescription: string

    if (retentionPeriod === RetentionPeriod.Month) {
        interval = 'week'
        intervalDescription = 'weeks per month'
    } else if (retentionPeriod === RetentionPeriod.Week) {
        interval = 'day'
        intervalDescription = 'days per week'
    } else if (retentionPeriod === RetentionPeriod.Hour) {
        interval = 'hour'
        intervalDescription = 'hours per day'
    } else {
        // Default to day for RetentionPeriod.Day
        interval = 'day'
        intervalDescription = 'days per week'
    }

    // Build the stickiness query
    const stickinessQuery: StickinessQuery = {
        kind: NodeKind.StickinessQuery,
        series,
        interval,
        dateRange: query.dateRange,
        properties: query.properties,
        filterTestAccounts: query.filterTestAccounts,
        stickinessFilter: {},
    }

    const stickinessTargetQuery: InsightVizNode = {
        kind: NodeKind.InsightVizNode,
        source: stickinessQuery,
    }

    // Build the lifecycle query
    const lifecycleQuery: LifecycleQuery = {
        kind: NodeKind.LifecycleQuery,
        series,
        interval,
        dateRange: query.dateRange,
        properties: query.properties,
        filterTestAccounts: query.filterTestAccounts,
        lifecycleFilter: {},
    }

    const lifecycleTargetQuery: InsightVizNode = {
        kind: NodeKind.InsightVizNode,
        source: lifecycleQuery,
    }

    return [
        {
            title: `Stickiness of users who performed ${entityDisplayName}`,
            description: `See how frequently retained users perform this event (${intervalDescription})`,
            targetQuery: stickinessTargetQuery,
        },
        {
            title: `Lifecycle of users who perform ${entityDisplayName}`,
            description: 'See lifecycle of users who perform this event (new vs returning vs resurrecting vs dormant)',
            targetQuery: lifecycleTargetQuery,
        },
    ]
}
