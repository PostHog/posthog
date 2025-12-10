/**
 * HogQL Type Resolver
 *
 * Resolves types for HogQL AST nodes by traversing the tree and:
 * 1. Resolving field references to table columns
 * 2. Assigning types to all expressions
 * 3. Expanding CTEs (Common Table Expressions)
 * 4. Handling table aliases and scopes
 *
 * Based on posthog/hogql/resolver.py
 */
import type * as ast from './ast'
import type { DatabaseSchema, DatabaseSchemaField, DatabaseSchemaTable } from './autocomplete'
import { CloningVisitor, cloneExpr } from './visitor'

// ====================================
// Database Interface
// ====================================

/**
 * Simple Database interface for resolving tables
 * Replaces Python's Database class with minimal functionality needed for resolution
 */
export class Database {
    private tables: Map<string, DatabaseSchemaTable>

    constructor(schema: DatabaseSchema) {
        this.tables = new Map(Object.entries(schema.tables))
    }

    hasTable(tableChain: string[]): boolean {
        const tableName = tableChain[0]
        return this.tables.has(tableName)
    }

    getTable(tableChain: string[]): DatabaseSchemaTable | null {
        const tableName = tableChain[0]
        return this.tables.get(tableName) || null
    }

    /**
     * Resolve a field from a table by traversing lazy tables and field chains
     */
    resolveField(table: DatabaseSchemaTable, fieldName: string): DatabaseSchemaTable | null {
        const field = table.fields[fieldName]
        if (!field) {
            return null
        }

        // If the field is a lazy_table or virtual_table, resolve to the actual table
        if (field.type === 'lazy_table' || field.type === 'virtual_table') {
            if (field.table) {
                return this.getTable([field.table])
            }
        }

        // If field has nested fields, treat it as a table-like structure
        // We need to create a virtual table structure for it
        if (field.fields && Array.isArray(field.fields)) {
            // This field points to another table's fields - we need to resolve them
            if (field.table) {
                const referencedTable = this.getTable([field.table])
                if (referencedTable) {
                    // Return a filtered version with only the specified fields
                    const filteredFields: Record<string, DatabaseSchemaField> = {}
                    for (const subFieldName of field.fields) {
                        if (referencedTable.fields[subFieldName]) {
                            filteredFields[subFieldName] = referencedTable.fields[subFieldName]
                        }
                    }
                    return {
                        ...referencedTable,
                        fields: filteredFields,
                    }
                }
            }
        }

        return null
    }
}

// ====================================
// Context
// ====================================

export interface HogQLContext {
    database: Database
    teamId?: number
    enableSelectQueries?: boolean
}

// ====================================
// Type Resolution
// ====================================

export function resolveTypes(
    node: ast.Expr,
    context: HogQLContext,
    dialect: 'hogql' | 'clickhouse' = 'clickhouse',
    scopes?: ast.SelectQueryType[]
): ast.Expr {
    const resolver = new Resolver(context, dialect, scopes)
    return resolver.visit(node) as ast.Expr
}

// ====================================
// Resolver Class
// ====================================

class Resolver extends CloningVisitor {
    scopes: ast.SelectQueryType[]
    context: HogQLContext
    dialect: 'hogql' | 'clickhouse'
    database: Database
    cteCounter: number = 0

    constructor(context: HogQLContext, dialect: 'hogql' | 'clickhouse' = 'clickhouse', scopes?: ast.SelectQueryType[]) {
        super()
        this.scopes = scopes || []
        this.context = context
        this.dialect = dialect
        this.database = context.database
    }

    visit(node: ast.AST | null | undefined): ast.AST | null | undefined {
        // Check if already resolved
        if (node && 'type' in node && (node as ast.Expr).type !== undefined) {
            throw new Error(
                `Type already resolved for ${node.type} (${(node as ast.Expr).type?.type}). Can't run again.`
            )
        }

        if (this.cteCounter > 50) {
            throw new Error('Too many CTE expansions (50+). Probably a CTE loop.')
        }

        return super.visit(node)
    }

    visit_select_query(node: ast.SelectQuery): ast.SelectQuery {
        // Create a new type/scope for this SELECT query
        const nodeType: ast.SelectQueryType = {
            tables: {},
            anonymous_tables: [],
            aliases: {},
            columns: {},
            ctes: node.ctes || ({} as any),
        }

        // Push scope early so child nodes can access it
        this.scopes.push(nodeType)

        // Clone the node
        const newNode: ast.SelectQuery = {
            ...node,
            type: nodeType,
            ctes: undefined, // CTEs are now in the type
            select: [], // Will be filled below
        }

        // Visit FROM clause first to resolve table aliases
        if (node.select_from) {
            newNode.select_from = this.visit(node.select_from) as ast.JoinExpr
        }

        // Visit SELECT columns
        const selectNodes: ast.Expr[] = []
        for (const expr of node.select || []) {
            const newExpr = this.visit(expr) as ast.Expr
            // TODO: Handle asterisk expansion
            selectNodes.push(newExpr)
        }

        // Collect aliases and column names
        for (const newExpr of selectNodes) {
            let alias: string | undefined

            // Check if type has an alias (FieldAliasType)
            if (newExpr.type && 'alias' in newExpr.type) {
                alias = (newExpr.type as ast.FieldAliasType).alias
            } else if (newExpr.type && 'name' in newExpr.type && 'table_type' in newExpr.type) {
                // FieldType or ExpressionFieldType
                alias = (newExpr.type as ast.FieldType | ast.ExpressionFieldType).name
            } else if ('alias' in newExpr && 'expr' in newExpr) {
                // This is an Alias node, not a type
                alias = (newExpr as ast.Alias).alias
            }

            if (alias) {
                nodeType.columns[alias] = newExpr.type!
            }

            newNode.select.push(newExpr)
        }

        // Visit other clauses
        if (node.where) {
            newNode.where = this.visit(node.where) as ast.Expr
        }
        if (node.having) {
            newNode.having = this.visit(node.having) as ast.Expr
        }
        if (node.group_by) {
            newNode.group_by = node.group_by.map((expr) => this.visit(expr) as ast.Expr)
        }
        if (node.order_by) {
            newNode.order_by = node.order_by.map((expr) => this.visit(expr) as ast.OrderExpr)
        }
        if (node.limit) {
            newNode.limit = this.visit(node.limit) as ast.Expr
        }
        if (node.offset) {
            newNode.offset = this.visit(node.offset) as ast.Expr
        }

        this.scopes.pop()

        return newNode
    }

    visit_join_expr(node: ast.JoinExpr): ast.JoinExpr {
        if (this.scopes.length === 0) {
            throw new Error('Unexpected JoinExpr outside a SELECT query')
        }

        const scope = this.scopes[this.scopes.length - 1]

        // Handle table references
        if (node.table && 'chain' in node.table) {
            const field = node.table as ast.Field
            const tableNameChain = field.chain.map((c) => String(c))
            const tableAlias = node.alias || tableNameChain.join('__')

            if (tableAlias in scope.tables) {
                throw new Error(`Already have joined a table called "${tableAlias}". Can't redefine.`)
            }

            // Look up table in database
            const databaseTable = this.database.getTable(tableNameChain)
            if (!databaseTable) {
                throw new Error(`Table "${tableNameChain.join('.')}" does not exist`)
            }

            // Create table type
            const nodeTableType: ast.TableType = {
                table: databaseTable,
            }

            const nodeType: ast.TableOrSelectType =
                tableAlias !== tableNameChain.join('__')
                    ? ({ alias: tableAlias, table_type: nodeTableType } as ast.TableAliasType)
                    : nodeTableType

            // Clone and update node
            const newNode: ast.JoinExpr = {
                ...node,
                type: nodeType,
                table: cloneExpr(field) as ast.Field,
            }

            // Update field type
            ;(newNode.table as ast.Field).type = nodeTableType

            // Add table to scope
            scope.tables[tableAlias] = nodeType

            // Visit next join
            if (node.next_join) {
                newNode.next_join = this.visit(node.next_join) as ast.JoinExpr
            }

            // Visit constraint
            if (node.constraint) {
                newNode.constraint = this.visit(node.constraint) as ast.JoinConstraint
            }

            return newNode
        }

        // Handle subqueries
        if (node.table && 'select' in node.table && Array.isArray((node.table as any).select)) {
            const newNode: ast.JoinExpr = {
                ...node,
                table: this.visit(node.table) as ast.SelectQuery,
            }

            const tableType = (newNode.table as ast.SelectQuery).type as ast.SelectQueryType

            if (node.alias) {
                const aliasType: ast.SelectQueryAliasType = {
                    alias: node.alias,
                    select_query_type: tableType,
                }
                newNode.type = aliasType
                scope.tables[node.alias] = aliasType
            } else {
                // If no alias, add as anonymous table
                newNode.type = tableType
                scope.anonymous_tables.push(tableType)
            }

            if (node.next_join) {
                newNode.next_join = this.visit(node.next_join) as ast.JoinExpr
            }

            if (node.constraint) {
                newNode.constraint = this.visit(node.constraint) as ast.JoinConstraint
            }

            return newNode
        }

        throw new Error(`A ${node.table?.type} cannot be used as a SELECT source`)
    }

    visit_alias(node: ast.Alias): ast.Alias {
        if (this.scopes.length === 0) {
            throw new Error('Aliases are allowed only within SELECT queries')
        }

        const scope = this.scopes[this.scopes.length - 1]
        if (node.alias in scope.aliases && !node.hidden) {
            throw new Error(`Cannot redefine an alias with the name: ${node.alias}`)
        }

        const newNode = super.visit_alias(node) as ast.Alias
        // Create FieldAliasType according to the AST definition
        const fieldAliasType: ast.FieldAliasType = {
            alias: node.alias,
            type: newNode.expr.type || ({ data_type: 'unknown', nullable: true } as ast.UnknownType),
        }
        newNode.type = fieldAliasType

        if (!node.hidden) {
            scope.aliases[node.alias] = fieldAliasType
        }

        return newNode
    }

    visit_field(node: ast.Field): ast.Expr {
        if (node.chain.length === 0) {
            throw new Error('Invalid field access with empty chain')
        }

        const newNode = super.visit_field(node) as ast.Field
        const scope = this.scopes[this.scopes.length - 1]
        const name = String(node.chain[0])

        // Check if it's a table reference
        let type: ast.Type | undefined = this.lookupTableByName(scope, newNode)

        // Check if it's a wildcard
        if (name === '*' && node.chain.length === 1) {
            const tableCount = scope.anonymous_tables.length + Object.keys(scope.tables).length
            if (tableCount === 0) {
                throw new Error("Cannot use '*' when there are no tables in the query")
            }
            if (tableCount > 1) {
                throw new Error("Cannot use '*' without table name when there are multiple tables in the query")
            }

            const tableType =
                scope.anonymous_tables.length > 0 ? scope.anonymous_tables[0] : Object.values(scope.tables)[0]

            type = { table_type: tableType } as ast.AsteriskType
        }

        // Check if it's a field in scope (column alias or table field)
        if (!type) {
            type = this.lookupFieldByName(scope, name)
        }

        if (!type) {
            if (this.dialect === 'clickhouse') {
                throw new Error(`Unable to resolve field: ${name}`)
            } else {
                type = { name } as ast.UnresolvedFieldType
            }
        }

        // Resolve the rest of the chain
        let loopType = type
        const chainToParse = node.chain.slice(1)

        while (chainToParse.length > 0) {
            const nextChain = chainToParse.shift()!
            loopType = this.getChildType(loopType, String(nextChain))
        }

        newNode.type = loopType

        // Wrap FieldType or UnresolvedFieldType in an alias
        // FieldType has: name, table_type
        // UnresolvedFieldType has: name
        if (newNode.type && 'name' in newNode.type && !('alias' in newNode.type)) {
            const fieldType = newNode.type as ast.FieldType | ast.UnresolvedFieldType
            const fieldName = String(node.chain[node.chain.length - 1]) || fieldType.name
            const fieldAliasType: ast.FieldAliasType = {
                alias: fieldType.name,
                type: newNode.type,
            }
            const aliasNode: ast.Alias = {
                alias: fieldName || fieldType.name,
                expr: newNode,
                hidden: true,
                type: fieldAliasType,
            }
            return aliasNode
        }

        return newNode
    }

    visit_constant(node: ast.Constant): ast.Constant {
        const newNode = super.visit_constant(node) as ast.Constant
        newNode.type = this.resolveConstantDataType(node.value)
        return newNode
    }

    visit_compare_operation(node: ast.CompareOperation): ast.CompareOperation {
        const newNode = super.visit_compare_operation(node) as ast.CompareOperation
        newNode.type = { data_type: 'bool', nullable: false } as ast.BooleanType
        return newNode
    }

    visit_and(node: ast.And): ast.And {
        const newNode = super.visit_and(node) as ast.And
        newNode.type = { data_type: 'bool', nullable: false } as ast.BooleanType
        return newNode
    }

    visit_or(node: ast.Or): ast.Or {
        const newNode = super.visit_or(node) as ast.Or
        newNode.type = { data_type: 'bool', nullable: false } as ast.BooleanType
        return newNode
    }

    visit_not(node: ast.Not): ast.Not {
        const newNode = super.visit_not(node) as ast.Not
        newNode.type = { data_type: 'bool', nullable: false } as ast.BooleanType
        return newNode
    }

    visit_arithmetic_operation(node: ast.ArithmeticOperation): ast.ArithmeticOperation {
        const newNode = super.visit_arithmetic_operation(node) as ast.ArithmeticOperation

        // Simple type inference for arithmetic
        // TODO: Add proper type inference based on operation
        newNode.type = { data_type: 'unknown', nullable: true } as ast.UnknownType

        return newNode
    }

    visit_call(node: ast.Call): ast.Call {
        const newNode = super.visit_call(node) as ast.Call

        // For now, all functions return UnknownType
        // TODO: Add function signature mappings
        newNode.type = {
            name: node.name,
            arg_types: [],
            param_types: [],
            return_type: { data_type: 'unknown', nullable: true } as ast.UnknownType,
        } as ast.CallType

        return newNode
    }

    // ====================================
    // Helper Methods
    // ====================================

    private lookupTableByName(scope: ast.SelectQueryType, node: ast.Field): ast.Type | undefined {
        // If the field has at least 2 parts, the first might be a table
        if (node.chain.length < 2) {
            return undefined
        }

        const name = String(node.chain[0])
        return scope.tables[name]
    }

    private lookupFieldByName(scope: ast.SelectQueryType, name: string): ast.Type | undefined {
        // Check aliases
        if (name in scope.aliases) {
            return scope.aliases[name]
        }

        // Check tables
        for (const tableType of Object.values(scope.tables)) {
            const childType = this.getChildType(tableType, name, true /* skipError */)
            if (childType) {
                return childType
            }
        }

        // Check anonymous tables
        for (const tableType of scope.anonymous_tables) {
            const childType = this.getChildType(tableType, name, true /* skipError */)
            if (childType) {
                return childType
            }
        }

        return undefined
    }

    private getChildType(type: ast.Type, name: string, skipError: boolean = false): ast.Type {
        // TableType: has 'table' property
        if ('table' in type && !('alias' in type)) {
            const tableType = type as ast.TableType
            const field = tableType.table.fields[name]

            if (!field) {
                if (skipError) {
                    return undefined as any
                }
                throw new Error(`Field "${name}" not found in table`)
            }

            // If field is a lazy_table or virtual_table, resolve to the actual table
            if (field.type === 'lazy_table' || field.type === 'virtual_table') {
                const resolvedTable = this.database.resolveField(tableType.table, name)
                if (resolvedTable) {
                    return { table: resolvedTable } as ast.TableType
                }
            }

            // If field is a field_traverser, follow the chain
            if (field.type === 'field_traverser' && field.chain) {
                let currentType: ast.Type = type
                for (const chainPart of field.chain) {
                    currentType = this.getChildType(currentType, String(chainPart), skipError)
                    if (!currentType) {
                        if (skipError) {
                            return undefined as any
                        }
                        throw new Error(`Cannot traverse chain at "${chainPart}"`)
                    }
                }
                return currentType
            }

            // Otherwise return as FieldType
            return {
                name: field.name,
                table_type: type,
            } as ast.FieldType
        }

        // TableAliasType: has 'alias' and 'table_type'
        if ('alias' in type && 'table_type' in type && !('select_query_type' in type)) {
            const aliasType = type as ast.TableAliasType
            return this.getChildType(aliasType.table_type, name, skipError)
        }

        // SelectQueryType: has 'columns', 'tables', 'aliases'
        if ('columns' in type && 'tables' in type && 'aliases' in type) {
            const selectType = type as ast.SelectQueryType
            if (name in selectType.columns) {
                return selectType.columns[name]
            }
            if (skipError) {
                return undefined as any
            }
            throw new Error(`Field "${name}" not found in subquery`)
        }

        // SelectQueryAliasType: has 'alias' and 'select_query_type'
        if ('alias' in type && 'select_query_type' in type) {
            const aliasType = type as ast.SelectQueryAliasType
            return this.getChildType(aliasType.select_query_type, name, skipError)
        }

        // FieldAliasType: has 'alias' and 'type' (and no other distinguishing fields from the above)
        if ('alias' in type && 'type' in type) {
            const aliasType = type as ast.FieldAliasType
            return this.getChildType(aliasType.type, name, skipError)
        }

        if (skipError) {
            return undefined as any
        }
        throw new Error(`Cannot get child "${name}" from type`)
    }

    private resolveConstantDataType(value: any): ast.Type {
        if (value === null || value === undefined) {
            return { data_type: 'unknown', nullable: true } as ast.UnknownType
        }
        if (typeof value === 'boolean') {
            return { data_type: 'bool', nullable: false } as ast.BooleanType
        }
        if (typeof value === 'number') {
            if (Number.isInteger(value)) {
                return { data_type: 'int', nullable: false } as ast.IntegerType
            }
            return { data_type: 'float', nullable: false } as ast.FloatType
        }
        if (typeof value === 'string') {
            return { data_type: 'str', nullable: false } as ast.StringType
        }
        if (Array.isArray(value)) {
            return {
                data_type: 'array',
                nullable: false,
                item_type: (value.length > 0
                    ? this.resolveConstantDataType(value[0])
                    : { data_type: 'unknown', nullable: true }) as ast.ConstantType,
            } as ast.ArrayType
        }
        return { data_type: 'unknown', nullable: true } as ast.UnknownType
    }
}
