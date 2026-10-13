import { ReactNode } from 'react'

import { ProductIconWrapper, iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { fileSystemTypes } from '~/products'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { SearchItem } from './searchItems'

export const getItemTypeDisplayName = (type: string | null | undefined): string | null => {
    if (!type) {
        return null
    }

    // Check fileSystemTypes manifest first
    if (type in fileSystemTypes) {
        return (fileSystemTypes as Record<string, { name?: string }>)[type]?.name ?? null
    }

    // Handle insight subtypes (e.g., 'insight/funnels' -> 'Funnel')
    if (type.startsWith('insight/')) {
        const subtype = type.slice(8) // Remove 'insight/' prefix
        const insightDisplayNames: Record<string, string> = {
            funnels: 'Funnel',
            trends: 'Trend',
            retention: 'Retention',
            paths: 'Paths',
            lifecycle: 'Lifecycle',
            stickiness: 'Stickiness',
            hog: 'SQL insight',
        }
        return insightDisplayNames[subtype] ?? null
    }

    // Fallback for types not in the manifest
    const fallbackDisplayNames: Record<string, string> = {
        query: 'SQL query',
        product_analytics: 'Product analytics',
        web_analytics: 'Web analytics',
        llm_analytics: 'AI observability',
        revenue_analytics: 'Revenue analytics',
        marketing_analytics: 'Marketing analytics',
        session_replay: 'Session replay',
        error_tracking: 'Error tracking',
        data_warehouse: 'Data ops',
        data_pipeline: 'Data pipeline',
        annotation: 'Annotation',
        event_definition: 'Event',
        property_definition: 'Property',
        person: 'Person',
        persons: 'Person',
        user: 'User',
        group: 'Group',
        account: 'Account',
        heatmap: 'Heatmap',
        sql_editor: 'SQL query',
        logs: 'Logs',
        alert: 'Alert',
        folder: 'Folder',
        hog_flow: 'Workflow',
    }
    return fallbackDisplayNames[type] ?? null
}

export const getIconForItem = (item: SearchItem): ReactNode => {
    if (item.icon) {
        return item.icon
    }
    let itemType = item.itemType || item.record?.type
    // Normalize types for icon lookup
    if (itemType === 'person') {
        itemType = 'persons'
    } else if (itemType === 'hog_flow') {
        itemType = 'workflows'
    }
    if (itemType) {
        // Handle iconColor which may be a single-element array or tuple
        const rawColor = item.record?.iconColor as string[] | undefined
        const colorOverride: [string, string] | undefined = rawColor
            ? rawColor.length === 1
                ? [rawColor[0], rawColor[0]]
                : [rawColor[0], rawColor[1]]
            : undefined
        return (
            <ProductIconWrapper type={itemType as string} colorOverride={colorOverride}>
                {iconForType(itemType as FileSystemIconType, colorOverride)}
            </ProductIconWrapper>
        )
    }
    return null
}
