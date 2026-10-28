import { DatabaseSchemaField } from '~/queries/schema/schema-general'

type TableLookupEntry = {
    name: string
    fields: Record<string, DatabaseSchemaField>
}

type TableLookup = Record<string, TableLookupEntry>

export const createVirtualTableField = (
    fieldName: string,
    parentField: DatabaseSchemaField,
    tableLookup?: TableLookup
): DatabaseSchemaField => {
    const referencedTable = parentField.table ? tableLookup?.[parentField.table] : undefined
    const referencedField = referencedTable?.fields?.[fieldName]

    if (referencedField) {
        return referencedField
    }

    return {
        name: fieldName,
        hogql_value: fieldName,
        type: 'unknown',
        schema_valid: true,
    }
}

const formatTraversalChain = (chain?: (string | number)[]): string | null => {
    if (!chain || chain.length === 0) {
        return null
    }

    return chain.map((segment) => String(segment)).join('.')
}

export const resolveFieldTraverserTarget = (
    tableName: string,
    field: DatabaseSchemaField,
    tableLookup?: TableLookup,
    visitedChains: Set<string> = new Set(),
    onUnloadedTable?: (tableName: string) => void
): DatabaseSchemaField | null => {
    if (!field.chain || !tableLookup) {
        return null
    }

    const traversalKey = JSON.stringify([tableName, field.chain])
    if (visitedChains.has(traversalKey)) {
        return null
    }
    visitedChains.add(traversalKey)

    const baseTable = tableLookup[tableName]
    if (!baseTable) {
        return null
    }

    let currentTable: TableLookupEntry | null = baseTable
    let currentField: DatabaseSchemaField | null = null
    let index = 0

    while (index < field.chain.length) {
        const segment: string | number = field.chain[index]
        const segmentKey = String(segment)

        if (segmentKey === '..') {
            return null
        }

        if (!currentField) {
            const nextField: DatabaseSchemaField | undefined = currentTable?.fields?.[segmentKey]
            if (!nextField) {
                if (currentTable && Object.keys(currentTable.fields ?? {}).length === 0) {
                    onUnloadedTable?.(currentTable.name)
                }
                return null
            }
            currentField = nextField
            index += 1
            continue
        }

        if (currentField.type === 'lazy_table') {
            currentTable = currentField.table ? (tableLookup[currentField.table] ?? null) : null
            currentField = null
            continue
        }

        if (currentField.type === 'virtual_table') {
            if (!currentField.fields?.includes(segmentKey)) {
                return null
            }
            currentField = createVirtualTableField(segmentKey, currentField, tableLookup)
            index += 1
            continue
        }

        if (currentField.type === 'field_traverser' && currentField.chain) {
            const chainKey = formatTraversalChain(currentField.chain)
            if (!chainKey || visitedChains.has(chainKey)) {
                return null
            }
            visitedChains.add(chainKey)
            currentField = resolveFieldTraverserTarget(
                tableName,
                currentField,
                tableLookup,
                visitedChains,
                onUnloadedTable
            )
            if (!currentField) {
                return null
            }
            continue
        }

        return null
    }

    if (currentField?.type === 'field_traverser') {
        return (
            resolveFieldTraverserTarget(tableName, currentField, tableLookup, visitedChains, onUnloadedTable) ??
            currentField
        )
    }

    return currentField
}
