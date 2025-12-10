/**
 * HogQL Autocomplete
 *
 * Provides autocomplete suggestions for HogQL queries by analyzing AST nodes
 * and database schema. Mirrors the Python implementation in posthog/hogql/autocomplete.py
 */
import { performQuery } from '~/queries/query'
import {
    AutocompleteCompletionItem,
    AutocompleteCompletionItemKind,
    DatabaseSchemaQuery,
    HogLanguage,
    HogQLAutocomplete,
    HogQLAutocompleteResponse,
    NodeKind,
} from '~/queries/schema/schema-general'
// ====================================
// Database Schema Types
// ====================================

import type {
    DatabaseSchemaField,
    DatabaseSchemaQueryResponse,
    DatabaseSchemaTable,
} from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'

import type * as ast from './ast'
import { isParseError, parseHogQLExpr, parseHogQLProgram, parseHogQLSelect, parseHogQLTemplateString } from './parser'
import { Database, type HogQLContext, resolveTypes } from './resolver'
import { TraversingVisitor, cloneExpr } from './visitor'

// Constants
const MATCH_ANY_CHARACTER = '$$_POSTHOG_ANY_$$'
const HOGQL_CHARACTERS_TO_BE_WRAPPED = [' ', '-', '.', ':', '[', ']', '(', ')']

// Re-export for convenience
export type { DatabaseSchemaField, DatabaseSchemaTable }
export type DatabaseSchema = DatabaseSchemaQueryResponse

// Singleton for database schema cache
let cachedDatabaseSchema: DatabaseSchema | null = null
let schemaFetchPromise: Promise<DatabaseSchema> | null = null

/**
 * Fetch and cache the database schema
 */
export async function getDatabaseSchema(): Promise<DatabaseSchema> {
    if (cachedDatabaseSchema) {
        return cachedDatabaseSchema
    }

    if (schemaFetchPromise) {
        return schemaFetchPromise
    }

    schemaFetchPromise = fetchDatabaseSchemaFromAPI()
    cachedDatabaseSchema = await schemaFetchPromise
    return cachedDatabaseSchema
}

/**
 * Reset the cached schema (useful for testing)
 */
export function resetDatabaseSchema(): void {
    cachedDatabaseSchema = null
    schemaFetchPromise = null
}

/**
 * Fetch database schema from API
 */
async function fetchDatabaseSchemaFromAPI(): Promise<DatabaseSchema> {
    const response = (await performQuery(
        setLatestVersionsOnQuery({ kind: NodeKind.DatabaseSchemaQuery }) as DatabaseSchemaQuery
    )) as DatabaseSchemaQueryResponse
    return response
}

// ====================================
// GetNodeAtPositionTraverser
// ====================================

/**
 * Visitor that finds the AST node at a specific position
 */
export class GetNodeAtPositionTraverser extends TraversingVisitor {
    start: number
    end: number
    selects: ast.SelectQuery[] = []
    node: ast.AST | null = null
    parentNode: ast.AST | null = null
    nearestSelectQuery: ast.SelectQuery | null = null
    private stack: ast.AST[] = []

    constructor(expr: ast.AST, start: number, end: number) {
        super()
        this.start = start
        this.end = end
        this.visit(expr)
    }

    visit(node: ast.AST | null | undefined): void {
        if (node != null && node.start != null && node.end != null) {
            const parentNode = this.stack.length > 0 ? this.stack[this.stack.length - 1] : null

            if (this.start >= node.start.offset && this.end <= node.end.offset) {
                this.node = node
                this.parentNode = parentNode
                if (this.selects.length > 0) {
                    this.nearestSelectQuery = this.selects[this.selects.length - 1]
                }
            } else if (
                parentNode &&
                ('declarations' in parentNode || parentNode.type === 'Program' || parentNode.type === 'Block')
            ) {
                // For Program and Block nodes, also capture nodes that start after the cursor
                // This helps with autocomplete at the end of statements like "return "
                if (
                    (this.node === null ||
                        this.node.type === 'Program' ||
                        this.node.type === 'Block' ||
                        ('declarations' in this.node && Array.isArray((this.node as any).declarations))) &&
                    node.start.offset >= this.start
                ) {
                    this.node = node
                    this.parentNode = parentNode
                }
            }
        }

        if (node != null) {
            this.stack.push(node)
            super.visit(node)
            this.stack.pop()
        } else {
            super.visit(node)
        }
    }

    visit_select_query(node: ast.SelectQuery): void {
        this.selects.push(node)
        super.visit_select_query(node)
        this.selects.pop()
    }
}

// ====================================
// Variable Finding
// ====================================

/**
 * Visitor that finds variables in scope at a specific node
 */
class VariableFinder extends TraversingVisitor {
    targetNode: ast.AST | null = null
    private stack: ast.AST[] = []
    private blocks: ast.AST[] = []
    private vars: Set<string>[] = []
    nodeVars: Set<string> = new Set()

    constructor(targetNode: ast.AST) {
        super()
        this.targetNode = targetNode
    }

    visit(node: ast.AST | null | undefined): void {
        if (node == null) {
            return
        }

        // Check if this is our target node - collect variables and stop traversing
        const isTarget = node === this.targetNode
        if (isTarget) {
            for (const blockVars of this.vars) {
                for (const v of blockVars) {
                    this.nodeVars.add(v)
                }
            }
            return // Stop here - don't visit children
        }

        const hasBlock =
            'declarations' in node &&
            (Array.isArray((node as any).declarations) || ('name' in node && 'params' in node && 'body' in node))

        if (hasBlock) {
            this.blocks.push(node)
            this.vars.push(new Set())
        }

        this.stack.push(node)
        super.visit(node)
        this.stack.pop()

        if (hasBlock) {
            this.blocks.pop()
            this.vars.pop()
        }
    }

    visit_variable_declaration(node: ast.VariableDeclaration): void {
        if (this.vars.length > 0) {
            this.vars[this.vars.length - 1].add(node.name)
        }
        super.visit_variable_declaration(node)
    }
}

/**
 * Gather all Hog variables in scope at a specific node
 */
function gatherHogVariablesInScope(rootNode: ast.AST, node: ast.AST): string[] {
    const finder = new VariableFinder(node)
    finder.visit(rootNode)
    return Array.from(finder.nodeVars)
}

// ====================================
// Suggestion Helpers
// ====================================

/**
 * Add suggestions to the response
 */
function extendResponses(
    keys: string[],
    suggestions: AutocompleteCompletionItem[],
    kind: AutocompleteCompletionItemKind = 'Variable',
    insertText?: (key: string) => string,
    details?: (string | null | undefined)[]
): void {
    suggestions.push(
        ...keys.map((key, index) => ({
            insertText: insertText ? insertText(key) : key,
            label: key,
            kind,
            detail: details && index < details.length ? (details[index] ?? undefined) : undefined,
        }))
    )
}

/**
 * Get table from a JoinExpr, handling CTEs and subqueries
 */
function getTableFromJoinExpr(
    joinExpr: ast.JoinExpr,
    schema: DatabaseSchema,
    ctes?: Record<string, ast.CTE>,
    resolvedCTEs?: Map<string, DatabaseSchemaTable>
): DatabaseSchemaTable | null {
    // Handle base table reference
    if (joinExpr.table && 'chain' in joinExpr.table) {
        const field = joinExpr.table as ast.Field
        const tableName = String(field.chain[0])

        // Check if it's a CTE
        if (ctes && tableName in ctes) {
            // Check if we've already resolved this CTE
            if (resolvedCTEs && resolvedCTEs.has(tableName)) {
                return resolvedCTEs.get(tableName)!
            }

            const cte = ctes[tableName]
            if ('select' in cte.expr && Array.isArray((cte.expr as any).select)) {
                const selectQuery = cte.expr as ast.SelectQuery
                // For CTEs, we need to resolve the CTE's SELECT query to get its columns
                // CTEs are not pre-resolved in the resolver, so we need to resolve them here
                try {
                    const database = new Database(schema)
                    const context: HogQLContext = {
                        database,
                        teamId: 1,
                        enableSelectQueries: true,
                    }
                    const resolvedCTE = resolveTypes(selectQuery, context, 'hogql') as ast.SelectQuery
                    if (resolvedCTE.type && 'columns' in resolvedCTE.type) {
                        const table = createTableFromColumns(resolvedCTE.type as ast.SelectQueryType, tableName)
                        // Cache the resolved CTE
                        if (resolvedCTEs) {
                            resolvedCTEs.set(tableName, table)
                        }
                        return table
                    }
                } catch {
                    // If resolution fails, continue
                }
            }
        }

        // Regular table lookup
        return schema.tables[tableName] || null
    }

    // Handle subquery
    if (joinExpr.table && 'select' in joinExpr.table && Array.isArray((joinExpr.table as any).select)) {
        const selectQuery = joinExpr.table as ast.SelectQuery
        // We need to resolve types for the subquery to extract its columns
        // This matches the Python implementation's resolve_fields_on_table()
        try {
            const database = new Database(schema)
            const context: HogQLContext = {
                database,
                teamId: 1,
                enableSelectQueries: true,
            }
            const resolvedSubquery = resolveTypes(selectQuery, context, 'hogql') as ast.SelectQuery
            if (resolvedSubquery.type && 'columns' in resolvedSubquery.type) {
                return createTableFromColumns(
                    resolvedSubquery.type as ast.SelectQueryType,
                    joinExpr.alias || 'subquery'
                )
            }
        } catch {
            // If resolution fails, continue
        }
    }

    return null
}

/**
 * Create a virtual DatabaseSchemaTable from resolved SELECT query columns
 */
function createTableFromColumns(selectType: ast.SelectQueryType, tableName: string): DatabaseSchemaTable {
    const fields: Record<string, DatabaseSchemaField> = {}

    for (const [columnName, columnType] of Object.entries(selectType.columns)) {
        // Extract the field type information
        let fieldType = 'unknown'

        if ('data_type' in columnType) {
            const constType = columnType as ast.ConstantType
            fieldType = constType.data_type
        } else if ('alias' in columnType && 'type' in columnType) {
            // FieldAliasType - get the underlying type
            const aliasType = columnType as ast.FieldAliasType
            if ('data_type' in aliasType.type) {
                const constType = aliasType.type as ast.ConstantType
                fieldType = constType.data_type
            }
        } else if ('name' in columnType) {
            // FieldType - this is a reference to another field
            fieldType = 'unknown'
        }

        fields[columnName] = {
            name: columnName,
            hogql_value: columnName,
            type: fieldType as any,
            schema_valid: true,
        }
    }

    return {
        type: 'posthog',
        id: tableName,
        name: tableName,
        fields,
    }
}

/**
 * Get all table aliases from a SELECT query (handling JOINs)
 */
function getTableAliases(
    selectQuery: ast.SelectQuery,
    schema: DatabaseSchema,
    ctes?: Record<string, ast.CTE>,
    resolvedCTEs?: Map<string, DatabaseSchemaTable>
): Record<string, DatabaseSchemaTable> {
    const aliases: Record<string, DatabaseSchemaTable> = {}

    if (!selectQuery.select_from) {
        return aliases
    }

    // Traverse the JOIN chain
    let currentJoin: ast.JoinExpr | null = selectQuery.select_from
    while (currentJoin) {
        const table = getTableFromJoinExpr(currentJoin, schema, ctes, resolvedCTEs)
        if (table && currentJoin.alias) {
            aliases[currentJoin.alias] = table
        } else if (table && currentJoin.table && 'chain' in currentJoin.table) {
            // If no alias, use the table name
            const field = currentJoin.table as ast.Field
            const tableName = String(field.chain[0])
            aliases[tableName] = table
        }

        currentJoin = currentJoin.next_join || null
    }

    return aliases
}

/**
 * Resolve a DatabaseSchemaField to a DatabaseSchemaTable if it references one
 */
function resolveFieldToTable(
    field: DatabaseSchemaField,
    schema: DatabaseSchema,
    currentTable?: DatabaseSchemaTable
): DatabaseSchemaTable | null {
    // If the field is a lazy_table or virtual_table, resolve to the actual table
    if (field.type === 'lazy_table' || field.type === 'virtual_table') {
        if (field.table) {
            return schema.tables[field.table] || null
        }
        // If it has fields but no table reference, create a virtual table structure
        if (field.fields && Array.isArray(field.fields)) {
            // This is unusual but we can't resolve it without a table reference
            return null
        }
    }

    // If field is a field_traverser, we need to follow the chain
    if (field.type === 'field_traverser' && field.chain && currentTable) {
        // Follow the chain to resolve the final table
        let resolvedTable: DatabaseSchemaTable | null = currentTable
        for (const chainPart of field.chain) {
            const chainPartStr = String(chainPart)
            const nextField = resolvedTable.fields[chainPartStr]
            if (!nextField) {
                return null
            }
            resolvedTable = resolveFieldToTable(nextField, schema, resolvedTable)
            if (!resolvedTable) {
                return null
            }
        }
        return resolvedTable
    }

    return null
}

/**
 * Capitalize type names for display (e.g., 'string' -> 'String', 'datetime' -> 'DateTime')
 */
function capitalizeTypeName(typeName: string | null | undefined): string | null {
    if (!typeName) {
        return null
    }

    // Special cases for compound type names
    const specialCases: Record<string, string> = {
        datetime: 'DateTime',
        boolean: 'Boolean',
        integer: 'Integer',
        json: 'JSON',
    }

    if (typeName in specialCases) {
        return specialCases[typeName]
    }

    // Default: capitalize first letter
    return typeName.charAt(0).toUpperCase() + typeName.slice(1)
}

/**
 * Add table fields to suggestions
 */
function appendTableFieldsToResponse(
    table: DatabaseSchemaTable,
    suggestions: AutocompleteCompletionItem[],
    language: HogLanguage
): void {
    const keys: string[] = []
    const details: (string | null)[] = []

    for (const [fieldName, field] of Object.entries(table.fields)) {
        keys.push(fieldName)
        details.push(capitalizeTypeName(field.type))
    }

    extendResponses(
        keys,
        suggestions,
        'Variable',
        (key) => (HOGQL_CHARACTERS_TO_BE_WRAPPED.some((char) => key.includes(char)) ? `\`${key}\`` : key),
        details
    )

    // Add functions
    const functions = language === HogLanguage.hogQL || language === HogLanguage.hogQLExpr ? HOGQL_FUNCTIONS : []
    extendResponses(functions, suggestions, 'Function', (key) => `${key}()`)
}

/**
 * Add globals to suggestions
 */
function addGlobalsToSuggestions(globals: Record<string, any>, response: HogQLAutocompleteResponse): void {
    const existingValues = new Set(response.suggestions.map((item) => item.label))
    const keys: string[] = []
    const values: (string | null)[] = []

    for (const [key, value] of Object.entries(globals)) {
        if (existingValues.has(key)) {
            continue
        }

        keys.push(key)

        if (typeof value === 'object' && value !== null) {
            if (Array.isArray(value)) {
                values.push('Array')
            } else {
                values.push('Object')
            }
        } else {
            const valueStr = JSON.stringify(value)
            values.push(valueStr.length > 20 ? valueStr.substring(0, 20) + '...' : valueStr)
        }
    }

    extendResponses(keys, response.suggestions, 'Variable', undefined, values)
}

/**
 * Extract JSON row from query (for HogJSON language)
 */
function extractJsonRow(queryToTry: string, queryStart: number, queryEnd: number): [string, number, number] {
    let queryRow = ''
    for (const row of queryToTry.split('\n')) {
        if (queryStart - row.length <= 0) {
            queryRow = row
            break
        }
        queryStart -= row.length + 1
        queryEnd -= row.length + 1
    }
    queryToTry = queryRow

    const count = queryToTry.substring(0, queryStart).split('"').length - 1
    if (count % 2 === 0) {
        // Not in a string
        return ['', 0, 0]
    }

    const startPos = queryToTry.lastIndexOf('"', queryStart - 1)
    const endPos = queryToTry.indexOf('"', queryStart)

    if (endPos === -1) {
        queryToTry = queryToTry.substring(startPos + 1)
    } else {
        queryToTry = queryToTry.substring(startPos + 1, endPos)
    }

    queryStart -= startPos + 1
    queryEnd -= startPos + 1

    return [queryToTry, queryStart, queryEnd]
}

// ====================================
// Main Autocomplete Function
// ====================================

// Basic HogQL functions list (subset)
const HOGQL_FUNCTIONS = [
    'toDateTime',
    'toString',
    'toInt',
    'toFloat',
    'now',
    'today',
    'dateDiff',
    'plus',
    'minus',
    'multiply',
    'divide',
    'concat',
    'length',
    'lower',
    'upper',
    'trim',
]

/**
 * Get HogQL autocomplete suggestions
 */
export async function getHogQLAutocomplete(query: HogQLAutocomplete): Promise<HogQLAutocompleteResponse> {
    const response: HogQLAutocompleteResponse = {
        suggestions: [],
        incomplete_list: false,
    }

    // Get database schema
    const schema = await getDatabaseSchema()

    // Source query for context (when in expression mode)
    let sourceQuery: ast.SelectQuery | null = null
    if (query.sourceQuery) {
        try {
            if (query.sourceQuery.kind === 'HogQLQuery') {
                const queryText = query.sourceQuery.query || 'select 1'
                const result = await parseHogQLSelect(queryText)
                if (!isParseError(result)) {
                    sourceQuery = result as ast.SelectQuery
                }
            }
        } catch {
            sourceQuery = null
        }
    }

    // Default source query if none provided
    if (!sourceQuery && query.language === HogLanguage.hogQLExpr) {
        try {
            const result = await parseHogQLSelect('select 1')
            if (!isParseError(result)) {
                sourceQuery = result as ast.SelectQuery
            }
        } catch {
            // Ignore
        }
    }

    // Try different completion strategies
    const attempts: [string, number][] = [
        ['', 0],
        [MATCH_ANY_CHARACTER, MATCH_ANY_CHARACTER.length],
        ['}', 0],
        [MATCH_ANY_CHARACTER + '}', MATCH_ANY_CHARACTER.length],
        [' FROM events', 0],
        [MATCH_ANY_CHARACTER + ' FROM events', MATCH_ANY_CHARACTER.length],
    ]

    for (const [extraCharacters, lengthToAdd] of attempts) {
        try {
            let queryToTry =
                query.query.substring(0, query.endPosition) + extraCharacters + query.query.substring(query.endPosition)
            let queryStart = query.startPosition
            let queryEnd = query.endPosition + lengthToAdd
            let rootNode: ast.AST | null = null
            let selectAst: ast.SelectQuery | null = null

            // Parse based on language
            if (query.language === HogLanguage.hogQL) {
                const result = await parseHogQLSelect(queryToTry)
                if (isParseError(result)) {
                    continue
                }
                rootNode = result
                selectAst = result as ast.SelectQuery
            } else if (query.language === HogLanguage.hogQLExpr) {
                const result = await parseHogQLExpr(queryToTry)
                if (isParseError(result)) {
                    continue
                }
                rootNode = result
                if (sourceQuery) {
                    selectAst = cloneExpr(sourceQuery, { clearLocations: true }) as ast.SelectQuery
                    selectAst.select = [rootNode as ast.Expr]
                }
            } else if (query.language === HogLanguage.hogTemplate) {
                const result = await parseHogQLTemplateString(queryToTry)
                if (isParseError(result)) {
                    continue
                }
                rootNode = result
            } else if (query.language === HogLanguage.hog) {
                const result = await parseHogQLProgram(queryToTry)
                if (isParseError(result)) {
                    continue
                }
                rootNode = result
            } else if (query.language === HogLanguage.hogJson) {
                const [queryToTry2, queryStart2, queryEnd2] = extractJsonRow(queryToTry, queryStart, queryEnd)

                queryToTry = queryToTry2
                queryStart = queryStart2
                queryEnd = queryEnd2

                if (queryToTry === '') {
                    break
                }

                const result = await parseHogQLTemplateString(queryToTry)
                if (isParseError(result)) {
                    continue
                }
                rootNode = result
            } else {
                continue
            }

            if (!rootNode) {
                continue
            }

            // Find node at position FIRST (before resolving types)
            const extra = query.language === HogLanguage.hogTemplate ? 2 : 0
            const findNode = new GetNodeAtPositionTraverser(rootNode, queryStart + extra, queryEnd + extra)
            const node = findNode.node
            const parentNode = findNode.parentNode

            // Note: We DON'T resolve types on the entire tree upfront like the old implementation did.
            // Instead, we resolve types only when needed (e.g., in getTableFromJoinExpr for subqueries).
            // This matches the Python implementation and avoids the issue of matching resolved nodes
            // to unresolved nodes after the tree is cloned by resolveTypes().

            // Skip if we're in a constant in a template string
            if (query.language === HogLanguage.hogTemplate && node && 'value' in node) {
                continue
            }

            // Handle globals
            if (query.globals && node && 'chain' in node) {
                const field = node as ast.Field
                let loopGlobals: Record<string, any> | null = query.globals

                for (let index = 0; index < field.chain.length; index++) {
                    const key = String(field.chain[index])
                    if (key.includes(MATCH_ANY_CHARACTER)) {
                        break
                    }

                    if (loopGlobals && key in loopGlobals) {
                        loopGlobals = loopGlobals[key]
                    } else if (index === field.chain.length - 1) {
                        break
                    } else {
                        loopGlobals = null
                        break
                    }
                }

                if (loopGlobals) {
                    addGlobalsToSuggestions(loopGlobals, response)
                    if (loopGlobals !== query.globals) {
                        break
                    }
                }
            }

            // Add Hog variables for Hog language
            if (
                query.language === HogLanguage.hog ||
                query.language === HogLanguage.hogTemplate ||
                query.language === HogLanguage.liquid
            ) {
                // For Hog, we need a specific node to find variables in scope
                // Use the found node, or try parent node, or fallback to a dummy end-of-program node
                let targetNode = node || parentNode
                if (!targetNode && rootNode) {
                    // Create a synthetic position at the end for variable gathering
                    targetNode = rootNode
                }
                if (targetNode) {
                    const hogVars = gatherHogVariablesInScope(rootNode, targetNode)
                    extendResponses(hogVars, response.suggestions, 'Variable')
                }
            }

            // Add globals
            if (query.globals) {
                const existingValues = new Set(response.suggestions.map((item) => item.label))
                const filteredGlobals: Record<string, any> = {}
                for (const [key, value] of Object.entries(query.globals)) {
                    if (!existingValues.has(key)) {
                        filteredGlobals[key] = value
                    }
                }
                addGlobalsToSuggestions(filteredGlobals, response)
            }

            // For Hog programs without SELECT queries, we're done after adding variables/globals
            if (
                !selectAst &&
                (query.language === HogLanguage.hog ||
                    query.language === HogLanguage.hogTemplate ||
                    query.language === HogLanguage.liquid)
            ) {
                break
            }

            if (!selectAst) {
                break
            }

            // Use the nearest SELECT from the traverser, or fall back to the root SELECT
            // This matches the Python implementation: nearest_select = find_node.nearest_select_query or select_ast
            const nearestSelect: ast.SelectQuery | null = findNode.nearestSelectQuery || selectAst
            const tableHasAlias =
                nearestSelect &&
                'select_from' in nearestSelect &&
                nearestSelect.select_from &&
                'alias' in nearestSelect.select_from &&
                nearestSelect.select_from.alias != null

            // Handle field suggestions
            // Exclude cases where parent is JoinExpr (table name context) or Placeholder
            if (
                node &&
                'chain' in node &&
                nearestSelect &&
                'select_from' in nearestSelect &&
                nearestSelect.select_from &&
                parentNode &&
                !('table' in parentNode) &&
                parentNode.type !== 'Placeholder'
            ) {
                const field = node as ast.Field
                const selectFrom = nearestSelect.select_from as ast.JoinExpr

                // Get CTEs from the nearest select query
                // After type resolution, CTEs are in the type, not directly on the node
                const ctes =
                    (nearestSelect.type && 'ctes' in nearestSelect.type
                        ? nearestSelect.type.ctes
                        : nearestSelect.ctes) || (selectAst?.ctes as Record<string, ast.CTE> | undefined)

                // Create cache for resolved CTEs
                const resolvedCTEs = new Map<string, DatabaseSchemaTable>()

                // Get the base table (handles CTEs, subqueries, and regular tables)
                let table = getTableFromJoinExpr(selectFrom, schema, ctes, resolvedCTEs)
                if (!table) {
                    continue
                }

                const chainLen = field.chain.length

                // Get all table aliases (for JOINs)
                const tableAliases = getTableAliases(nearestSelect, schema, ctes, resolvedCTEs)

                // Check if the FROM is a subquery without an alias - if so, use its columns directly
                const isAnonymousSubquery =
                    selectFrom.table &&
                    'select' in selectFrom.table &&
                    Array.isArray((selectFrom.table as any).select) &&
                    !selectFrom.alias

                // Handle table alias suggestion
                if (tableHasAlias && chainLen === 1 && !isAnonymousSubquery) {
                    const aliasNames = Object.keys(tableAliases)
                    extendResponses(
                        aliasNames,
                        response.suggestions,
                        'Folder',
                        undefined,
                        aliasNames.map(() => 'Table')
                    )
                    break
                }

                // Check if the first chain part is a table alias
                if (chainLen > 0 && tableHasAlias && !isAnonymousSubquery) {
                    const firstPart = String(field.chain[0])
                    if (firstPart in tableAliases) {
                        table = tableAliases[firstPart]
                        // Start navigation from index 1
                        const remainingChain = field.chain.slice(1)
                        if (remainingChain.length === 0) {
                            // Just the alias, show all fields
                            appendTableFieldsToResponse(table, response.suggestions, query.language)
                            break
                        }
                        // Navigate through remaining chain
                        let currentTable: DatabaseSchemaTable = table
                        for (let index = 0; index < remainingChain.length; index++) {
                            const chainPart = String(remainingChain[index])
                            const isLastPart = index >= remainingChain.length - 2

                            if (isLastPart) {
                                const currentField = currentTable.fields[chainPart]
                                if (currentField) {
                                    const resolvedTable = resolveFieldToTable(currentField, schema, currentTable)
                                    if (resolvedTable) {
                                        appendTableFieldsToResponse(resolvedTable, response.suggestions, query.language)
                                    } else {
                                        // Field exists but can't be resolved to a table (e.g., json field)
                                        // Still show functions as suggestions
                                        const functions =
                                            query.language === HogLanguage.hogQL || query.language === HogQLExpr
                                                ? HOGQL_FUNCTIONS
                                                : []
                                        extendResponses(
                                            functions,
                                            response.suggestions,
                                            'Function',
                                            (key) => `${key}()`
                                        )
                                    }
                                } else {
                                    appendTableFieldsToResponse(currentTable, response.suggestions, query.language)
                                }
                                break
                            }

                            const currentField = currentTable.fields[chainPart]
                            if (currentField) {
                                const resolvedTable = resolveFieldToTable(currentField, schema, currentTable)
                                if (resolvedTable) {
                                    currentTable = resolvedTable
                                } else {
                                    break
                                }
                            } else {
                                break
                            }
                        }
                        break
                    } else {
                        // When table has alias but first part doesn't match any alias,
                        // don't show suggestions (invalid reference)
                        break
                    }
                }

                // Navigate through field chain (no alias)
                let currentTable: DatabaseSchemaTable = table
                for (let index = 0; index < chainLen; index++) {
                    const chainPart = String(field.chain[index])
                    const isLastPart = index >= chainLen - 2

                    if (isLastPart) {
                        // Check if this chain part exists in the current table
                        const currentField = currentTable.fields[chainPart]
                        if (currentField) {
                            // The field exists, check if it references another table
                            const resolvedTable = resolveFieldToTable(currentField, schema, currentTable)
                            if (resolvedTable) {
                                appendTableFieldsToResponse(resolvedTable, response.suggestions, query.language)
                            } else {
                                // Field exists but can't be resolved to a table (e.g., json field)
                                // Still show functions as suggestions
                                const functions =
                                    query.language === HogLanguage.hogQL || query.language === HogLanguage.hogQLExpr
                                        ? HOGQL_FUNCTIONS
                                        : []
                                extendResponses(functions, response.suggestions, 'Function', (key) => `${key}()`)
                            }
                        } else {
                            // The field doesn't exist, show all fields at current level
                            appendTableFieldsToResponse(currentTable, response.suggestions, query.language)
                        }
                        break
                    }

                    // Navigate to the next level
                    const currentField = currentTable.fields[chainPart]
                    if (currentField) {
                        const resolvedTable = resolveFieldToTable(currentField, schema, currentTable)
                        if (resolvedTable) {
                            currentTable = resolvedTable
                        } else {
                            break
                        }
                    } else {
                        break
                    }
                }
            } else if (node && 'chain' in node && parentNode && 'table' in parentNode) {
                // Handle table name suggestions
                const tableNames = Object.keys(schema.tables)
                extendResponses(
                    tableNames,
                    response.suggestions,
                    'Folder',
                    undefined,
                    tableNames.map(() => 'Table')
                )
            }

            if (response.suggestions.length > 0) {
                break
            }
        } catch {
            // Continue to next attempt
            continue
        }

        if (response.suggestions.length > 0) {
            break
        }
    }

    return response
}
