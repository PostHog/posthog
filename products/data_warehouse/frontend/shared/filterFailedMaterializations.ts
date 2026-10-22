import type { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

export function filterFailedMaterializations(items: TreeDataItem[]): TreeDataItem[] {
    return items.flatMap((item) => {
        if (item.record?.type === 'view') {
            return item.record.view?.is_materialized && item.record.view.status === 'Failed' ? [item] : []
        }

        if (item.type === 'loading-indicator') {
            return [item]
        }

        if (item.record?.type === 'views' || item.record?.folderType === 'view-folder') {
            const children = filterFailedMaterializations(item.children ?? [])
            return children.length ? [{ ...item, children }] : []
        }

        return []
    })
}
