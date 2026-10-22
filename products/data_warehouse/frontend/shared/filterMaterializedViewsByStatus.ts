import type { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

export const MATERIALIZATION_STATUS_FILTER_OPTIONS = ['Failed', 'Running', 'Completed'] as const
export type MaterializationStatusFilter = (typeof MATERIALIZATION_STATUS_FILTER_OPTIONS)[number]

export function filterMaterializedViewsByStatus(
    items: TreeDataItem[],
    statuses: MaterializationStatusFilter[]
): TreeDataItem[] {
    if (statuses.length === 0) {
        return items
    }

    return items.flatMap((item) => {
        if (item.record?.type === 'view') {
            return item.record.view?.is_materialized && statuses.includes(item.record.view.status) ? [item] : []
        }

        if (item.type === 'loading-indicator') {
            return [item]
        }

        if (item.record?.type === 'views' || item.record?.folderType === 'view-folder') {
            const children = filterMaterializedViewsByStatus(item.children ?? [], statuses)
            return children.length ? [{ ...item, children }] : []
        }

        return []
    })
}
