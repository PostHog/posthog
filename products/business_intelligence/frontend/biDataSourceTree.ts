import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { BIDataSource } from '~/queries/schema/schema-business-intelligence'

import { getBIDataSourceKey } from 'products/business_intelligence/frontend/biEditorTypes'
import { groupDirectConnectionTableNodesBySchema } from 'products/data_warehouse/frontend/shared/connectionTableTree'

function certificationRank(item: TreeDataItem): number {
    if (item.children?.length) {
        return Math.min(...item.children.map(certificationRank))
    }
    return item.record?.certification?.status === 'certified'
        ? 0
        : item.record?.certification?.status === 'deprecated'
          ? 2
          : 1
}

function prioritizeCertifiedSources(tree: TreeDataItem[]): TreeDataItem[] {
    return tree
        .map((item) => (item.children ? { ...item, children: prioritizeCertifiedSources(item.children) } : item))
        .sort((a, b) => certificationRank(a) - certificationRank(b))
}

export function buildBIDataSourceTree(
    tree: TreeDataItem[],
    sources: BIDataSource[],
    directConnection: boolean,
    defaultSchemaName?: string | null,
    connectionId?: string | null
): TreeDataItem[] {
    const remaining = new Map(sources.map((source) => [getBIDataSourceKey(source), source]))
    const leaves: TreeDataItem[] = []
    const certified: TreeDataItem[] = []
    const visit = (items: TreeDataItem[]): TreeDataItem[] =>
        items.flatMap((item) => {
            if (['table', 'view', 'managed-view', 'view-table', 'endpoint'].includes(item.record?.type)) {
                const tableName = item.record?.type === 'endpoint' ? item.record.tableName : item.name
                const source = remaining.get(
                    getBIDataSourceKey({ table: tableName, connectionId: connectionId ?? undefined })
                )
                if (!source) {
                    return []
                }
                remaining.delete(getBIDataSourceKey(source))
                const node: TreeDataItem = {
                    id: getBIDataSourceKey(source),
                    name: source.table,
                    icon: item.icon,
                    record: { ...item.record, type: item.record?.type },
                }
                if (node.record?.certification?.status === 'certified') {
                    certified.push(node)
                    return []
                }
                leaves.push(node)
                return [node]
            }
            const children = visit(item.children ?? [])
            return children.length
                ? [{ id: item.id, name: item.name, icon: item.icon, record: { type: item.record?.type }, children }]
                : []
        })
    const grouped = visit(tree)
    const missing = [...remaining.values()].map((source) => ({ id: getBIDataSourceKey(source), name: source.table }))
    return [
        ...(certified.length ? [{ id: 'bi-certified-sources', name: 'Certified sources', children: certified }] : []),
        ...prioritizeCertifiedSources(
            directConnection
                ? groupDirectConnectionTableNodesBySchema([...leaves, ...missing], false, defaultSchemaName)
                : [...grouped, ...missing]
        ),
    ]
}

export function searchBIDataSourceTree(tree: TreeDataItem[], search: string): TreeDataItem[] {
    const term = search.trim().toLocaleLowerCase()
    return prioritizeCertifiedSources(
        tree.flatMap((item) => {
            if (item.name.toLocaleLowerCase().includes(term)) {
                return [item]
            }
            const children = searchBIDataSourceTree(item.children ?? [], term)
            return children.length ? [{ ...item, children }] : []
        })
    )
}

export function getBIDataSourceFolderIds(tree: TreeDataItem[]): string[] {
    return tree.flatMap((item) => (item.children?.length ? [item.id, ...getBIDataSourceFolderIds(item.children)] : []))
}
