import { FileSystemImport } from '~/queries/schema/schema-general'

import { CATEGORY_ORDER, DATA_MANAGEMENT_PANEL_ORDER, splitPath, unescapePath } from '../../ProjectTree/utils'

export interface AppsItemGroup {
    label: string
    items: FileSystemImport[]
}

export function appsItemName(item: FileSystemImport): string {
    return item.displayLabel || unescapePath(splitPath(item.path).pop() ?? item.path)
}

const categoryOrder = [
    'Project',
    ...new Set([
        ...CATEGORY_ORDER,
        ...Object.entries(DATA_MANAGEMENT_PANEL_ORDER)
            .sort(([, a], [, b]) => a - b)
            .map(([category]) => category),
    ]),
]

export function groupApps(items: FileSystemImport[], search: string): AppsItemGroup[] {
    const query = search.trim().toLowerCase()
    const groups = new Map<string, FileSystemImport[]>()
    for (const item of items) {
        if (query && !`${appsItemName(item)} ${item.path}`.toLowerCase().includes(query)) {
            continue
        }
        const category = item.category || 'Other'
        const group = groups.get(category) ?? []
        group.push(item)
        groups.set(category, group)
    }
    const orderOf = (category: string): number => {
        const index = categoryOrder.indexOf(category)
        return index === -1 ? categoryOrder.length : index
    }
    return [...groups.entries()]
        .sort(([a], [b]) => orderOf(a) - orderOf(b) || a.localeCompare(b))
        .map(([label, entries]) => ({
            label,
            items: entries.sort(
                (a, b) =>
                    (a.visualOrder ?? Infinity) - (b.visualOrder ?? Infinity) ||
                    appsItemName(a).localeCompare(appsItemName(b), undefined, { sensitivity: 'accent' })
            ),
        }))
}
