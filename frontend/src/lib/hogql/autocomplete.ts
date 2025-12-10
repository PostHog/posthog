/**
 * HogQL Autocomplete
 *
 * Provides autocomplete suggestions for HogQL queries by analyzing AST nodes
 * and database schema. Mirrors the Python implementation in posthog/hogql/autocomplete.py
 */
import {
    AutocompleteCompletionItem,
    AutocompleteCompletionItemKind,
    HogLanguage,
    HogQLAutocomplete,
    HogQLAutocompleteResponse,
} from '~/queries/schema/schema-general'

import type * as ast from './ast'
import { isParseError, parseHogQLExpr, parseHogQLProgram, parseHogQLSelect, parseHogQLTemplateString } from './parser'
import { TraversingVisitor, cloneExpr } from './visitor'

// Constants
const MATCH_ANY_CHARACTER = '$$_POSTHOG_ANY_$$'
const HOGQL_CHARACTERS_TO_BE_WRAPPED = [' ', '-', '.', ':', '[', ']', '(', ')']

// ====================================
// Database Schema Types
// ====================================

export interface DatabaseField {
    name: string
    type?: string
    hidden?: boolean
}

export interface DatabaseTable {
    name: string
    fields: Record<string, DatabaseField | DatabaseTable>
}

export interface DatabaseSchema {
    tables: Record<string, DatabaseTable>
}

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
 * For now, returns a mock schema - will be replaced with actual API call
 */
async function fetchDatabaseSchemaFromAPI(): Promise<DatabaseSchema> {
    // TODO: Replace with actual API call to externalDataSources.database_schema
    // For now, return a basic schema structure
    return {
        tables: {
            events: {
                name: 'events',
                fields: {
                    uuid: { name: 'uuid', type: 'String' },
                    event: { name: 'event', type: 'String' },
                    timestamp: { name: 'timestamp', type: 'DateTime' },
                    distinct_id: { name: 'distinct_id', type: 'String' },
                    properties: { name: 'properties', type: 'Object' },
                    person_id: { name: 'person_id', type: 'String' },
                    person_properties: { name: 'person_properties', type: 'Object' },
                    pdi: {
                        name: 'pdi',
                        fields: {
                            distinct_id: { name: 'distinct_id', type: 'String' },
                            person_id: { name: 'person_id', type: 'String' },
                            team_id: { name: 'team_id', type: 'Integer' },
                            version: { name: 'version', type: 'Integer' },
                        },
                    },
                },
            },
            persons: {
                name: 'persons',
                fields: {
                    id: { name: 'id', type: 'String' },
                    created_at: { name: 'created_at', type: 'DateTime' },
                    properties: { name: 'properties', type: 'Object' },
                    is_identified: { name: 'is_identified', type: 'Boolean' },
                },
            },
        },
    }
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
            } else if ((parentNode && 'declarations' in parentNode) || (parentNode && 'declarations' in parentNode)) {
                if (
                    (this.node === null ||
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

        if (node === this.targetNode) {
            for (const blockVars of this.vars) {
                for (const v of blockVars) {
                    this.nodeVars.add(v)
                }
            }
            return
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
 * Add table fields to suggestions
 */
function appendTableFieldsToResponse(
    table: DatabaseTable,
    suggestions: AutocompleteCompletionItem[],
    language: HogLanguage
): void {
    const keys: string[] = []
    const details: (string | null)[] = []

    for (const [fieldName, field] of Object.entries(table.fields)) {
        // Skip hidden fields
        if ('hidden' in field && field.hidden) {
            continue
        }

        keys.push(fieldName)
        details.push(field.type ?? null)
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
            sourceQuery = (await parseHogQLSelect('select * from events')) as ast.SelectQuery
        } catch {
            sourceQuery = null
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

            // Find node at position
            const extra = query.language === HogLanguage.hogTemplate ? 2 : 0
            const findNode = new GetNodeAtPositionTraverser(rootNode, queryStart + extra, queryEnd + extra)
            const node = findNode.node
            const parentNode = findNode.parentNode

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
                if (node) {
                    const hogVars = gatherHogVariablesInScope(rootNode, node)
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

            if (!selectAst) {
                break
            }

            const nearestSelect = findNode.nearestSelectQuery || selectAst
            const tableHasAlias =
                nearestSelect &&
                'select_from' in nearestSelect &&
                nearestSelect.select_from &&
                'alias' in nearestSelect.select_from &&
                nearestSelect.select_from.alias != null

            // Handle field suggestions
            if (
                node &&
                'chain' in node &&
                nearestSelect &&
                'select_from' in nearestSelect &&
                nearestSelect.select_from &&
                parentNode &&
                !('table' in parentNode) &&
                !('expr' in parentNode && 'chain' in parentNode)
            ) {
                const field = node as ast.Field
                const selectFrom = nearestSelect.select_from as ast.JoinExpr

                // Get table from schema
                let tableName = 'events'
                if (selectFrom.table && 'chain' in selectFrom.table) {
                    const tableField = selectFrom.table as ast.Field
                    tableName = String(tableField.chain[0])
                }

                const table = schema.tables[tableName]
                if (!table) {
                    continue
                }

                const chainLen = field.chain.length

                // Handle table alias
                if (tableHasAlias && chainLen === 1) {
                    const alias = (selectFrom as any).alias
                    if (alias) {
                        extendResponses([alias], response.suggestions, 'Folder', undefined, ['Table'])
                    }
                    break
                }

                // Navigate through field chain
                let currentTable: DatabaseTable | DatabaseField = table
                for (let index = 0; index < chainLen; index++) {
                    const chainPart = String(field.chain[index])
                    const isLastPart = index >= chainLen - 2

                    if (isLastPart) {
                        if ('fields' in currentTable) {
                            appendTableFieldsToResponse(currentTable, response.suggestions, query.language)
                        }
                        break
                    }

                    if ('fields' in currentTable && chainPart in currentTable.fields) {
                        currentTable = currentTable.fields[chainPart]
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
