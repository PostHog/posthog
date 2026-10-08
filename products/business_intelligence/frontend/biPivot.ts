import { BIConfig } from '~/queries/schema/schema-business-intelligence'

import { getBIResultDimensions } from './biEditorTypes'

export interface BIPivotMember {
    key: string
    path: unknown[]
    label: string
    children: BIPivotMember[]
}

export interface BIPivotModel {
    rows: BIPivotMember[]
    columns: BIPivotMember[]
    cells: Map<string, Record<string, unknown>>
}

export function biPivotKey(path: unknown[]): string {
    return JSON.stringify(path)
}

export function biPivotCellKey(row: unknown[], column: unknown[]): string {
    return JSON.stringify([row, column])
}

export function buildBIPivotModel(config: BIConfig, columns: string[], results: unknown[][]): BIPivotModel {
    const dimensions = getBIResultDimensions(config)
    const rowCount = config.rows.filter((field) => field.expression.trim() || field.name.trim()).length
    const columnCount = config.columns.filter((field) => field.expression.trim() || field.name.trim()).length
    const summaries = rowCount > 1 || columnCount > 1 || !!(config.totals?.rows || config.totals?.columns)
    const model: BIPivotModel = { rows: [], columns: [], cells: new Map() }
    const indexes = new Map(columns.map((column, index) => [column, index]))
    const members = { rows: new Map<string, BIPivotMember>(), columns: new Map<string, BIPivotMember>() }
    const readPath = (row: unknown[], side: 'rows' | 'columns'): unknown[] => {
        const fields = side === 'rows' ? dimensions.slice(0, rowCount) : dimensions.slice(rowCount)
        const values = fields.map(({ column, position }) => {
            const value = row[indexes.get(column)!]
            if (position === undefined) {
                return value
            }
            try {
                const tuple = typeof value === 'string' ? JSON.parse(value) : value
                return Array.isArray(tuple) ? tuple[position] : undefined
            } catch {
                return undefined
            }
        })
        const depth = summaries ? values.indexOf('Total') : -1
        return depth === -1 ? values : values.slice(0, depth)
    }
    const addPath = (path: unknown[], side: 'rows' | 'columns'): void => {
        if (!path.length) {
            if (!(side === 'rows' ? config.totals?.columns : config.totals?.rows) || members[side].has('[]')) {
                return
            }
            const total = { key: '[]', path, label: 'Total', children: [] }
            members[side].set('[]', total)
            model[side].push(total)
        }
        for (let depth = 1; depth <= path.length; depth++) {
            const prefix = path.slice(0, depth)
            const key = biPivotKey(prefix)
            if (!members[side].has(key)) {
                const member: BIPivotMember = {
                    key,
                    path: prefix,
                    label: String(prefix[depth - 1] ?? '(empty)'),
                    children: [],
                }
                members[side].set(key, member)
                const siblings =
                    depth === 1 ? model[side] : members[side].get(biPivotKey(prefix.slice(0, -1)))!.children
                siblings.push(member)
            }
        }
    }
    for (const result of results) {
        const row = readPath(result, 'rows')
        const column = readPath(result, 'columns')
        addPath(row, 'rows')
        addPath(column, 'columns')
        model.cells.set(
            biPivotCellKey(row, column),
            Object.fromEntries(columns.map((name, index) => [name, result[index]]))
        )
    }
    // Grand totals stay after their detail members, regardless of query sorting.
    for (const side of ['rows', 'columns'] as const) {
        model[side].sort((a, b) => Number(!a.path.length) - Number(!b.path.length))
    }
    return model
}

export function visibleBIPivotMembers(
    members: BIPivotMember[],
    collapsed: Set<string>,
    includeParents: boolean
): BIPivotMember[] {
    return members.flatMap((member) => {
        if (!member.children.length || collapsed.has(member.key)) {
            return [member]
        }
        return [
            ...(includeParents ? [member] : []),
            ...visibleBIPivotMembers(member.children, collapsed, includeParents),
        ]
    })
}
