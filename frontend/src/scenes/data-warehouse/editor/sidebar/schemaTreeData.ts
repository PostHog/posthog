import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { escapeDottedHogQLIdentifier } from 'lib/utils/hogql'

/**
 * The text a column row inserts at the cursor, or null when there is nothing to insert.
 *
 * The name has to be checked rather than assumed: escaping an undefined one throws, and a throw
 * escapes the tree row's `<a>` click handler before it can preventDefault, so the browser follows
 * the row's placeholder href and leaves the scene the tree is embedded in.
 */
export function getColumnInsertText(record: Record<string, any> | undefined): string | null {
    if (record?.type !== 'column' || !record.columnName) {
        return null
    }
    if (typeof record.hogqlExpression === 'string') {
        return record.hogqlExpression
    }
    return escapeDottedHogQLIdentifier(record.columnName)
}

export function getTooltipDescription(record: Record<string, any> | undefined): string | undefined {
    switch (record?.type) {
        case 'column':
            return record.field?.description || undefined
        case 'table':
            return record.table?.description || undefined
        case 'view':
            return record.view?.description || undefined
        default:
            return undefined
    }
}

/**
 * Keep a section whose folder, or any of its children, matches the search term — the same
 * name-and-field matching the database tree does for its own tables.
 */
const filterTreeSections = (sections: TreeDataItem[], searchTerm: string): TreeDataItem[] => {
    const needle = searchTerm.trim().toLowerCase()
    if (!needle) {
        return sections
    }
    const matches = (item: TreeDataItem): boolean =>
        item.name.toLowerCase().includes(needle) || (item.children ?? []).some(matches)
    return sections.flatMap((section) => {
        const children = (section.children ?? []).filter(matches)
        return children.length ? [{ ...section, children }] : []
    })
}

export const getQueryDatabaseTreeData = (
    displayedTreeData: TreeDataItem[],
    extraTreeSections: TreeDataItem[] | undefined,
    searchText: string
): TreeDataItem[] => {
    if (!extraTreeSections?.length) {
        return displayedTreeData
    }

    return [...filterTreeSections(extraTreeSections, searchText), ...displayedTreeData]
}

export const formatTraversalChain = (chain?: (string | number)[]): string | null => {
    if (!chain || chain.length === 0) {
        return null
    }
    return chain.map((segment) => String(segment)).join('.')
}

export function getSchemaItemTooltip(item: TreeDataItem): { title: string; description?: string } | undefined {
    const tooltipTypes = ['table', 'view', 'managed-view', 'draft', 'metric', 'column', 'unsaved-query', 'folder']
    if (item.record?.type === 'endpoint') {
        return { title: item.name, description: 'Materialized endpoint' }
    }
    if (tooltipTypes.includes(item.record?.type)) {
        let label = item.name
        if (item.record?.type === 'column' && item.record?.field?.type === 'field_traverser') {
            const traversalChain = formatTraversalChain(item.record.field.chain)
            if (traversalChain) {
                label = `${item.name} → ${traversalChain}`
            }
        }
        const description = getTooltipDescription(item.record)
        if (!description) {
            return label === item.name ? undefined : { title: label }
        }
        return { title: label, description }
    }
    if (item.record?.type === 'source-folder' && item.record?.sourceType === 'System') {
        return {
            title: 'Query PostHog project metadata, such as saved insights, dashboards, and feature flags, plus query logs and schema information.',
        }
    }
    if (item.record?.type === 'field-traverser') {
        const traversalChain = formatTraversalChain(item.record?.field?.chain)
        return { title: traversalChain ? `${item.name} → ${traversalChain}` : item.name }
    }
    return undefined
}
