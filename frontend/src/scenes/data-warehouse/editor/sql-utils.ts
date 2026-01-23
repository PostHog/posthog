export const normalizeIdentifier = (identifier: string): string => {
    return identifier.replace(/^[`"']|[`"']$/g, '').toLowerCase()
}

export const escapeIdentifier = (identifier: string): string => {
    const escaped = identifier.replace(/`/g, '``')
    return `\`${escaped}\``
}

const parseSelectedColumns = (selectedColumns: string): string[] => {
    return selectedColumns
        .split(',')
        .map((column) => column.trim())
        .filter((column) => column.length > 0)
}

export const buildQueryForColumnClick = (
    currentQuery: string | null,
    tableName: string,
    columnName: string
): string => {
    const limitOffsetClause = currentQuery ? extractLimitOffsetClause(currentQuery) : null
    const escapedTable = escapeIdentifier(tableName)
    const escapedColumn = escapeIdentifier(columnName)
    const baseQuery = `select ${escapedColumn} from ${escapedTable} ${limitOffsetClause ?? 'limit 100'}`

    if (!currentQuery) {
        return baseQuery
    }

    const match = currentQuery.match(/^\s*select\s+([\s\S]+?)\s+from\s+([^\s;]+)[\s\S]*$/i)

    if (!match) {
        return baseQuery
    }

    const [, selectedColumnsRaw, selectedTableRaw] = match

    if (normalizeIdentifier(selectedTableRaw) !== normalizeIdentifier(tableName)) {
        return baseQuery
    }

    let columns = parseSelectedColumns(selectedColumnsRaw).map(normalizeIdentifier)
    const normalizedColumnName = normalizeIdentifier(columnName)
    const isStarOnly = columns.length === 1 && columns[0] === '*'

    if (isStarOnly) {
        columns = []
    } else {
        columns = columns.filter((column) => column !== '*')
    }

    const existingIndex = columns.findIndex((column) => column === normalizedColumnName)

    if (existingIndex >= 0) {
        columns.splice(existingIndex, 1)
    } else {
        columns.push(normalizedColumnName)
    }

    if (columns.length === 0) {
        columns = ['*']
    }

    const escapedColumns = columns.map((col) => (col === '*' ? col : escapeIdentifier(col)))
    return `select ${escapedColumns.join(', ')} from ${escapedTable} ${limitOffsetClause ?? 'limit 100'}`
}

const normalizeKeywordSpacing = (query: string): string => {
    return query.replace(/\s+/g, ' ').trim()
}

const extractLimitOffsetClause = (query: string): string | null => {
    const matches = Array.from(query.matchAll(/\b(limit\s+\d+(?:\s+offset\s+\d+)?|offset\s+\d+)\b/gi))

    if (matches.length === 0) {
        return null
    }

    return matches[matches.length - 1][0].replace(/;$/, '').trim()
}

export const parseQueryTablesAndColumns = (queryInput: string | null): Record<string, Record<string, boolean>> => {
    if (!queryInput) {
        return {}
    }

    const normalizedQuery = normalizeKeywordSpacing(queryInput)
    const selectMatch = normalizedQuery.match(/\bselect\b\s+(.+?)\s+\bfrom\b\s+(.+)/i)

    if (!selectMatch) {
        return {}
    }

    const [, rawColumns, rawFrom] = selectMatch
    const columns = parseSelectedColumns(rawColumns)
    const fromClause = rawFrom.split(/\bwhere\b|\bgroup\b|\border\b|\blimit\b/i)[0] ?? ''
    const tableMatches = `from ${fromClause}`.match(/\bfrom\b\s+([^\s,]+)|\bjoin\b\s+([^\s,]+)/gi) ?? []
    const tables = tableMatches
        .flatMap((match) => match.split(/\s+/).slice(1))
        .map((table) => table.replace(/,$/, ''))
        .filter((table) => table.length > 0)
    const selectedTables = Array.from(new Set(tables))

    const selectedColumnsByTable: Record<string, Record<string, boolean>> = {}

    if (selectedTables.length === 0) {
        return selectedColumnsByTable
    }

    columns.forEach((column) => {
        if (column === '*') {
            selectedTables.forEach((table) => {
                selectedColumnsByTable[table] = {
                    '*': true,
                    ...selectedColumnsByTable[table],
                }
            })
            return
        }

        const [tablePrefix, columnName] = column.split('.')
        if (
            columnName &&
            selectedTables.some((table) => normalizeIdentifier(table) === normalizeIdentifier(tablePrefix))
        ) {
            const tableKey = selectedTables.find(
                (table) => normalizeIdentifier(table) === normalizeIdentifier(tablePrefix)
            ) as string
            selectedColumnsByTable[tableKey] = {
                [columnName]: true,
                ...selectedColumnsByTable[tableKey],
            }
            return
        }

        const fallbackTable = selectedTables[0]
        selectedColumnsByTable[fallbackTable] = {
            [column]: true,
            ...selectedColumnsByTable[fallbackTable],
        }
    })

    return selectedColumnsByTable
}
