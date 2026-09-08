import { objectClean } from 'lib/utils/objects'

import { AnyEntityNode, GroupNode } from '~/queries/schema/schema-general'
import { isDataWarehouseNode, isEventsNode } from '~/queries/utils'
import { EntityTypes, InsightLogicProps, RetentionEntity } from '~/types'

export const CUSTOMER_ANALYTICS_LOGIC_KEY = 'customerAnalytics'

export const buildDashboardItemId = (uniqueKey: string): InsightLogicProps['dashboardItemId'] => {
    return `new-AdHoc.customer-analytics.${uniqueKey}`
}

export function isPageviewWithoutFilters(event: AnyEntityNode | GroupNode): boolean {
    return isEventsNode(event) && event.event === '$pageview' && (!event.properties || event.properties.length === 0)
}

/** Retention takes a legacy entity rather than a series node, so map the configured event onto one. */
export function toRetentionEntity(node: AnyEntityNode): RetentionEntity {
    if (isDataWarehouseNode(node)) {
        return objectClean({
            type: EntityTypes.DATA_WAREHOUSE,
            id: node.id,
            name: node.name,
            properties: node.properties,
            table_name: node.table_name,
            timestamp_field: node.timestamp_field,
            aggregation_target_field: node.distinct_id_field,
        })
    }
    if (isEventsNode(node)) {
        return objectClean({
            type: EntityTypes.EVENTS,
            id: node.event ?? undefined,
            name: node.name ?? node.event ?? undefined,
            properties: node.properties,
        })
    }
    return objectClean({
        type: EntityTypes.ACTIONS,
        id: node.id,
        name: node.name,
        properties: node.properties,
    })
}
