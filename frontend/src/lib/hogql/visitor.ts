// oxlint-disable no-unused-vars
/**
 * HogQL AST Visitor Pattern
 *
 * Provides visitor pattern implementation for traversing and transforming HogQL AST nodes.
 * Mirrors the Python implementation in posthog/hogql/visitor.py
 */
import type * as ast from './ast'

// ====================================
// Utility Functions
// ====================================

/**
 * Clone an expression node
 */
export function cloneExpr<T extends ast.AST>(
    expr: T,
    options: {
        clearTypes?: boolean
        clearLocations?: boolean
        inlineSubqueryFieldNames?: boolean
    } = {}
): T {
    return new CloningVisitor(
        options.clearTypes ?? true,
        options.clearLocations ?? false,
        options.inlineSubqueryFieldNames ?? false
    ).visit(expr) as T
}

/**
 * Clear location information from an expression
 */
export function clearLocations<T extends ast.AST>(expr: T): T {
    return new CloningVisitor(true, true, false).visit(expr) as T
}

/**
 * Check if a value is a simple primitive value
 */
function isSimpleValue(value: any): boolean {
    return (
        value === null ||
        value === undefined ||
        typeof value === 'string' ||
        typeof value === 'number' ||
        typeof value === 'boolean'
    )
}

// ====================================
// Base Visitor
// ====================================

/**
 * Base visitor class for traversing AST nodes
 * Generic parameter T is the return type of visit methods
 */
export abstract class Visitor<T> {
    visit(node: ast.AST | null | undefined): T {
        if (node == null) {
            return node as any
        }

        // Determine the node type and call appropriate visit method
        const nodeType = this.getNodeType(node)
        const methodName = `visit_${nodeType}` as keyof this
        const method = this[methodName]

        if (typeof method === 'function') {
            return (method as any).call(this, node)
        }

        throw new Error(`No visit method for node type: ${nodeType}`)
    }

    private getNodeType(node: ast.AST): string {
        // Type guard: ensure node is an object before using 'in' operator
        if (typeof node !== 'object' || node === null) {
            throw new Error(`Invalid node type: expected object, got ${typeof node}`)
        }

        // Convert TypeScript interface types to snake_case method names
        // This matches the Python implementation's convention
        if ('declarations' in node && !('expr' in node)) {
            if ('name' in node && 'params' in node && 'body' in node) {
                return 'function'
            }
            if ('declarations' in node && Array.isArray((node as any).declarations)) {
                if ('start' in node && 'end' in node && !('name' in node)) {
                    return 'block'
                }
                return 'program'
            }
        }

        // Statements
        if ('body' in node) {
            if ('condition' in node && 'increment' in node) {
                return 'for_statement'
            }
            if ('expr' in node && 'then' in node) {
                return 'if_statement'
            }
            if ('expr' in node && 'body' in node) {
                return 'while_statement'
            }
            if ('valueVar' in node) {
                return 'for_in_statement'
            }
        }
        if ('try_stmt' in node) {
            return 'try_catch_statement'
        }
        if ('left' in node && 'right' in node && !('op' in node)) {
            return 'variable_assignment'
        }
        if ('name' in node && 'expr' in node && !('alias' in node) && !('cte_type' in node)) {
            return 'variable_declaration'
        }

        // Expressions
        if ('alias' in node && 'expr' in node) {
            return 'alias'
        }
        if ('op' in node) {
            if ('left' in node && 'right' in node) {
                const op = (node as any).op
                if (['+', '-', '*', '/', '%'].includes(op)) {
                    return 'arithmetic_operation'
                }
                return 'compare_operation'
            }
        }
        if ('exprs' in node && Array.isArray((node as any).exprs)) {
            if ('n' in node) {
                return 'limit_by_expr'
            }
            // Differentiate And/Or/Array/Tuple
            const firstExpr = (node as any).exprs[0]
            if (firstExpr && typeof firstExpr === 'object') {
                // And/Or are pure logic nodes, check if there's other identifying fields
                if (!('value' in node) && !('tuple' in node)) {
                    // This is a heuristic - in practice we'd need better type discrimination
                    return 'array' // Default to array for now
                }
            }
            return 'tuple'
        }
        if ('expr' in node && !('alias' in node)) {
            if ('low' in node && 'high' in node) {
                return 'between_expr'
            }
            if ('order' in node) {
                return 'order_expr'
            }
            if ('tuple' in node) {
                return 'tuple_access'
            }
            if ('then' in node) {
                return 'if_statement'
            }
            if ('body' in node) {
                return 'while_statement'
            }
            // Check Lambda before ExprCall since both have 'args' and no 'name'
            // Lambda has args: string[], ExprCall has args: Expr[]
            if ('args' in node && Array.isArray((node as any).args) && !('name' in node)) {
                // Check if first arg is a string to distinguish Lambda from ExprCall
                const args = (node as any).args
                if (args.length === 0 || typeof args[0] === 'string') {
                    return 'lambda'
                }
                return 'expr_call'
            }
            if ('chain' in node || 'field' in node) {
                return 'placeholder'
            }
            if (!('name' in node)) {
                return 'expr_statement'
            }
            return 'not'
        }
        if ('name' in node && 'args' in node) {
            return 'call'
        }
        if ('chain' in node) {
            return 'field'
        }
        if ('value' in node) {
            return 'constant'
        }
        if ('array' in node) {
            return 'array_access'
        }
        if ('left' in node && 'right' in node) {
            return 'ratio_expr'
        }
        if ('sample_value' in node) {
            return 'sample_expr'
        }

        // Query nodes
        if ('select' in node && Array.isArray((node as any).select)) {
            return 'select_query'
        }
        if ('initial_select_query' in node) {
            return 'select_set_query'
        }
        if ('set_operator' in node) {
            return 'select_set_node'
        }
        if ('table' in node && !('value' in node)) {
            return 'join_expr'
        }
        if ('constraint_type' in node) {
            return 'join_constraint'
        }

        // Window expressions
        if ('partition_by' in node || 'order_by' in node) {
            if ('name' in node && 'over_expr' in node) {
                return 'window_function'
            }
            return 'window_expr'
        }
        if ('frame_type' in node) {
            return 'window_frame_expr'
        }

        // CTE
        if ('cte_type' in node) {
            return 'cte'
        }

        // HogQLX
        if ('kind' in node && 'attributes' in node) {
            return 'hogqlx_tag'
        }
        if ('name' in node && 'value' in node && !('expr' in node)) {
            return 'hogqlx_attribute'
        }

        // Types
        if ('data_type' in node) {
            const dataType = (node as any).data_type
            if (dataType === 'int') {
                return 'integer_type'
            }
            if (dataType === 'float') {
                return 'float_type'
            }
            if (dataType === 'str') {
                return 'string_type'
            }
            if (dataType === 'bool') {
                return 'boolean_type'
            }
            if (dataType === 'date') {
                return 'date_type'
            }
            if (dataType === 'datetime') {
                return 'date_time_type'
            }
            if (dataType === 'uuid') {
                return 'uuid_type'
            }
            if (dataType === 'array') {
                return 'array_type'
            }
            if (dataType === 'tuple') {
                return 'tuple_type'
            }
            return 'unknown_type'
        }

        // Return statement
        if ('expr' in node && Object.keys(node).length <= 3) {
            return 'return_statement'
        }

        throw new Error(`Unknown node type: ${JSON.stringify(Object.keys(node))}`)
    }

    // Abstract visit methods - subclasses must implement these
    abstract visit_cte(node: ast.CTE): T
    abstract visit_alias(node: ast.Alias): T
    abstract visit_arithmetic_operation(node: ast.ArithmeticOperation): T
    abstract visit_and(node: ast.And): T
    abstract visit_or(node: ast.Or): T
    abstract visit_compare_operation(node: ast.CompareOperation): T
    abstract visit_not(node: ast.Not): T
    abstract visit_between_expr(node: ast.BetweenExpr): T
    abstract visit_order_expr(node: ast.OrderExpr): T
    abstract visit_tuple_access(node: ast.TupleAccess): T
    abstract visit_tuple(node: ast.Tuple): T
    abstract visit_lambda(node: ast.Lambda): T
    abstract visit_array_access(node: ast.ArrayAccess): T
    abstract visit_array(node: ast.Array): T
    abstract visit_dict(node: ast.Dict): T
    abstract visit_constant(node: ast.Constant): T
    abstract visit_field(node: ast.Field): T
    abstract visit_placeholder(node: ast.Placeholder): T
    abstract visit_call(node: ast.Call): T
    abstract visit_expr_call(node: ast.ExprCall): T
    abstract visit_sample_expr(node: ast.SampleExpr): T
    abstract visit_ratio_expr(node: ast.RatioExpr): T
    abstract visit_join_expr(node: ast.JoinExpr): T
    abstract visit_join_constraint(node: ast.JoinConstraint): T
    abstract visit_select_query(node: ast.SelectQuery): T
    abstract visit_select_set_query(node: ast.SelectSetQuery): T
    abstract visit_select_set_node(node: ast.SelectSetNode): T
    abstract visit_window_expr(node: ast.WindowExpr): T
    abstract visit_window_function(node: ast.WindowFunction): T
    abstract visit_window_frame_expr(node: ast.WindowFrameExpr): T
    abstract visit_hogqlx_tag(node: ast.HogQLXTag): T
    abstract visit_hogqlx_attribute(node: ast.HogQLXAttribute): T
    abstract visit_program(node: ast.Program): T
    abstract visit_limit_by_expr(node: ast.LimitByExpr): T
    abstract visit_block(node: ast.Block): T
    abstract visit_if_statement(node: ast.IfStatement): T
    abstract visit_while_statement(node: ast.WhileStatement): T
    abstract visit_for_statement(node: ast.ForStatement): T
    abstract visit_for_in_statement(node: ast.ForInStatement): T
    abstract visit_expr_statement(node: ast.ExprStatement): T
    abstract visit_return_statement(node: ast.ReturnStatement): T
    abstract visit_throw_statement(node: ast.ThrowStatement): T
    abstract visit_try_catch_statement(node: ast.TryCatchStatement): T
    abstract visit_function(node: ast.Function): T
    abstract visit_variable_declaration(node: ast.VariableDeclaration): T
    abstract visit_variable_assignment(node: ast.VariableAssignment): T

    // Type visitor methods
    abstract visit_lambda_argument_type(node: ast.LambdaArgumentType): T
    abstract visit_field_alias_type(node: ast.FieldAliasType): T
    abstract visit_field_type(node: ast.FieldType): T
    abstract visit_select_query_type(node: ast.SelectQueryType): T
    abstract visit_select_set_query_type(node: ast.SelectSetQueryType): T
    abstract visit_table_type(node: ast.TableType): T
    abstract visit_lazy_table_type(node: ast.LazyTableType): T
    abstract visit_field_traverser_type(node: ast.FieldTraverserType): T
    abstract visit_lazy_join_type(node: ast.LazyJoinType): T
    abstract visit_virtual_table_type(node: ast.VirtualTableType): T
    abstract visit_table_alias_type(node: ast.TableAliasType): T
    abstract visit_select_query_alias_type(node: ast.SelectQueryAliasType): T
    abstract visit_select_view_type(node: ast.SelectViewType): T
    abstract visit_asterisk_type(node: ast.AsteriskType): T
    abstract visit_call_type(node: ast.CallType): T
    abstract visit_integer_type(node: ast.IntegerType): T
    abstract visit_float_type(node: ast.FloatType): T
    abstract visit_decimal_type(node: ast.DecimalType): T
    abstract visit_string_type(node: ast.StringType): T
    abstract visit_string_json_type(node: ast.StringJSONType): T
    abstract visit_string_array_type(node: ast.StringArrayType): T
    abstract visit_boolean_type(node: ast.BooleanType): T
    abstract visit_unknown_type(node: ast.UnknownType): T
    abstract visit_array_type(node: ast.ArrayType): T
    abstract visit_tuple_type(node: ast.TupleType): T
    abstract visit_date_type(node: ast.DateType): T
    abstract visit_date_time_type(node: ast.DateTimeType): T
    abstract visit_interval_type(node: ast.IntervalType): T
    abstract visit_uuid_type(node: ast.UUIDType): T
    abstract visit_property_type(node: ast.PropertyType): T
    abstract visit_expression_field_type(node: ast.ExpressionFieldType): T
    abstract visit_unresolved_field_type(node: ast.UnresolvedFieldType): T
}

// ====================================
// TraversingVisitor
// ====================================

/**
 * Visitor that traverses the AST tree without returning anything
 */
export class TraversingVisitor extends Visitor<void> {
    visit_cte(node: ast.CTE): void {
        this.visit(node.expr)
    }

    visit_alias(node: ast.Alias): void {
        this.visit(node.expr)
    }

    visit_arithmetic_operation(node: ast.ArithmeticOperation): void {
        this.visit(node.left)
        this.visit(node.right)
    }

    visit_and(node: ast.And): void {
        for (const expr of node.exprs) {
            this.visit(expr)
        }
    }

    visit_or(node: ast.Or): void {
        for (const expr of node.exprs) {
            this.visit(expr)
        }
    }

    visit_compare_operation(node: ast.CompareOperation): void {
        this.visit(node.left)
        this.visit(node.right)
    }

    visit_not(node: ast.Not): void {
        this.visit(node.expr)
    }

    visit_between_expr(node: ast.BetweenExpr): void {
        this.visit(node.expr)
        this.visit(node.low)
        this.visit(node.high)
    }

    visit_order_expr(node: ast.OrderExpr): void {
        this.visit(node.expr)
    }

    visit_tuple_access(node: ast.TupleAccess): void {
        this.visit(node.tuple)
    }

    visit_tuple(node: ast.Tuple): void {
        for (const expr of node.exprs) {
            this.visit(expr)
        }
    }

    visit_lambda(node: ast.Lambda): void {
        this.visit(node.expr)
    }

    visit_array_access(node: ast.ArrayAccess): void {
        this.visit(node.array)
        this.visit(node.property)
    }

    visit_array(node: ast.Array): void {
        for (const expr of node.exprs) {
            this.visit(expr)
        }
    }

    visit_dict(node: ast.Dict): void {
        for (const [key, value] of node.items) {
            this.visit(key)
            this.visit(value)
        }
    }

    visit_constant(node: ast.Constant): void {
        if (node.type) {
            this.visit(node.type)
        }
    }

    visit_field(node: ast.Field): void {
        if (node.type) {
            this.visit(node.type)
        }
    }

    visit_placeholder(node: ast.Placeholder): void {
        this.visit(node.expr)
    }

    visit_call(node: ast.Call): void {
        for (const arg of node.args) {
            this.visit(arg)
        }
        if (node.params) {
            for (const param of node.params) {
                this.visit(param)
            }
        }
    }

    visit_expr_call(node: ast.ExprCall): void {
        this.visit(node.expr)
        for (const arg of node.args) {
            this.visit(arg)
        }
    }

    visit_sample_expr(node: ast.SampleExpr): void {
        this.visit(node.sample_value)
        if (node.offset_value) {
            this.visit(node.offset_value)
        }
    }

    visit_ratio_expr(node: ast.RatioExpr): void {
        this.visit(node.left)
        if (node.right) {
            this.visit(node.right)
        }
    }

    visit_join_expr(node: ast.JoinExpr): void {
        if (node.table) {
            this.visit(node.table as any)
        }
        if (node.table_args) {
            for (const arg of node.table_args) {
                this.visit(arg)
            }
        }
        if (node.constraint) {
            this.visit(node.constraint)
        }
        if (node.next_join) {
            this.visit(node.next_join)
        }
        if (node.sample) {
            this.visit(node.sample)
        }
    }

    visit_select_query(node: ast.SelectQuery): void {
        if (node.select_from) {
            this.visit(node.select_from)
        }
        if (node.ctes) {
            for (const cte of Object.values(node.ctes)) {
                this.visit(cte)
            }
        }
        if (node.array_join_list) {
            for (const expr of node.array_join_list) {
                this.visit(expr)
            }
        }
        for (const expr of node.select) {
            this.visit(expr)
        }
        if (node.where) {
            this.visit(node.where)
        }
        if (node.prewhere) {
            this.visit(node.prewhere)
        }
        if (node.having) {
            this.visit(node.having)
        }
        if (node.group_by) {
            for (const expr of node.group_by) {
                this.visit(expr)
            }
        }
        if (node.order_by) {
            for (const expr of node.order_by) {
                this.visit(expr)
            }
        }
        if (node.limit_by) {
            this.visit(node.limit_by)
        }
        if (node.limit) {
            this.visit(node.limit)
        }
        if (node.offset) {
            this.visit(node.offset)
        }
        if (node.window_exprs) {
            for (const expr of Object.values(node.window_exprs)) {
                this.visit(expr)
            }
        }
    }

    visit_select_set_query(node: ast.SelectSetQuery): void {
        this.visit(node.initial_select_query as any)
        for (const subsequent of node.subsequent_select_queries) {
            this.visit(subsequent.select_query as any)
        }
    }

    visit_select_set_node(node: ast.SelectSetNode): void {
        this.visit(node.select_query as any)
    }

    visit_lambda_argument_type(_node: ast.LambdaArgumentType): void {
        // No nested nodes to visit
    }

    visit_field_alias_type(node: ast.FieldAliasType): void {
        this.visit(node.type)
    }

    visit_field_type(_node: ast.FieldType): void {
        // No nested nodes to visit
    }

    visit_select_query_type(node: ast.SelectQueryType): void {
        for (const table of Object.values(node.tables)) {
            this.visit(table as any)
        }
        for (const anon of node.anonymous_tables) {
            this.visit(anon as any)
        }
        for (const alias of Object.values(node.aliases)) {
            this.visit(alias)
        }
        for (const col of Object.values(node.columns)) {
            this.visit(col)
        }
    }

    visit_select_set_query_type(node: ast.SelectSetQueryType): void {
        for (const type of node.types) {
            this.visit(type as any)
        }
    }

    visit_table_type(_node: ast.TableType): void {
        // No nested nodes to visit
    }

    visit_lazy_table_type(_node: ast.LazyTableType): void {
        // No nested nodes to visit
    }

    visit_field_traverser_type(node: ast.FieldTraverserType): void {
        this.visit(node.table_type as any)
    }

    visit_lazy_join_type(node: ast.LazyJoinType): void {
        this.visit(node.table_type as any)
    }

    visit_virtual_table_type(node: ast.VirtualTableType): void {
        this.visit(node.table_type as any)
    }

    visit_table_alias_type(node: ast.TableAliasType): void {
        this.visit(node.table_type as any)
    }

    visit_select_query_alias_type(node: ast.SelectQueryAliasType): void {
        this.visit(node.select_query_type as any)
    }

    visit_select_view_type(node: ast.SelectViewType): void {
        this.visit(node.select_query_type as any)
    }

    visit_asterisk_type(node: ast.AsteriskType): void {
        this.visit(node.table_type as any)
    }

    visit_call_type(node: ast.CallType): void {
        for (const argType of node.arg_types) {
            this.visit(argType)
        }
        if (node.param_types) {
            for (const paramType of node.param_types) {
                this.visit(paramType)
            }
        }
        this.visit(node.return_type)
    }

    visit_integer_type(_node: ast.IntegerType): void {
        // No nested nodes to visit
    }

    visit_float_type(_node: ast.FloatType): void {
        // No nested nodes to visit
    }

    visit_decimal_type(_node: ast.DecimalType): void {
        // No nested nodes to visit
    }

    visit_string_type(_node: ast.StringType): void {
        // No nested nodes to visit
    }

    visit_string_json_type(_node: ast.StringJSONType): void {
        // No nested nodes to visit
    }

    visit_string_array_type(_node: ast.StringArrayType): void {
        // No nested nodes to visit
    }

    visit_boolean_type(_node: ast.BooleanType): void {
        // No nested nodes to visit
    }

    visit_unknown_type(_node: ast.UnknownType): void {
        // No nested nodes to visit
    }

    visit_array_type(node: ast.ArrayType): void {
        this.visit(node.item_type)
    }

    visit_tuple_type(node: ast.TupleType): void {
        for (const itemType of node.item_types) {
            this.visit(itemType)
        }
    }

    visit_date_type(_node: ast.DateType): void {
        // No nested nodes to visit
    }

    visit_date_time_type(_node: ast.DateTimeType): void {
        // No nested nodes to visit
    }

    visit_interval_type(_node: ast.IntervalType): void {
        // No nested nodes to visit
    }

    visit_uuid_type(_node: ast.UUIDType): void {
        // No nested nodes to visit
    }

    visit_property_type(node: ast.PropertyType): void {
        this.visit(node.field_type)
    }

    visit_expression_field_type(_node: ast.ExpressionFieldType): void {
        // No nested nodes to visit
    }

    visit_unresolved_field_type(_node: ast.UnresolvedFieldType): void {
        // No nested nodes to visit
    }

    visit_window_expr(node: ast.WindowExpr): void {
        if (node.partition_by) {
            for (const expr of node.partition_by) {
                this.visit(expr)
            }
        }
        if (node.order_by) {
            for (const expr of node.order_by) {
                this.visit(expr)
            }
        }
        if (node.frame_start) {
            this.visit(node.frame_start)
        }
        if (node.frame_end) {
            this.visit(node.frame_end)
        }
    }

    visit_window_function(node: ast.WindowFunction): void {
        if (node.exprs) {
            for (const expr of node.exprs) {
                this.visit(expr)
            }
        }
        if (node.args) {
            for (const arg of node.args) {
                this.visit(arg)
            }
        }
        if (node.over_expr) {
            this.visit(node.over_expr)
        }
    }

    visit_window_frame_expr(_node: ast.WindowFrameExpr): void {
        // No nested nodes to visit
    }

    visit_join_constraint(node: ast.JoinConstraint): void {
        this.visit(node.expr)
    }

    visit_hogqlx_tag(node: ast.HogQLXTag): void {
        for (const attribute of node.attributes) {
            this.visit(attribute)
        }
    }

    visit_hogqlx_attribute(node: ast.HogQLXAttribute): void {
        if (Array.isArray(node.value)) {
            for (const value of node.value) {
                if (isSimpleValue(value)) {
                    this.visit({ value } as ast.Constant)
                } else {
                    this.visit(value)
                }
            }
        } else {
            this.visit(node.value as any)
        }
    }

    visit_program(node: ast.Program): void {
        for (const decl of node.declarations) {
            this.visit(decl)
        }
    }

    visit_limit_by_expr(node: ast.LimitByExpr): void {
        this.visit(node.n)
        if (node.offset_value) {
            this.visit(node.offset_value)
        }
        for (const expr of node.exprs) {
            this.visit(expr)
        }
    }

    visit_block(node: ast.Block): void {
        for (const decl of node.declarations) {
            this.visit(decl)
        }
    }

    visit_if_statement(node: ast.IfStatement): void {
        this.visit(node.expr)
        this.visit(node.then)
        if (node.else_) {
            this.visit(node.else_)
        }
    }

    visit_while_statement(node: ast.WhileStatement): void {
        this.visit(node.expr)
        this.visit(node.body)
    }

    visit_for_statement(node: ast.ForStatement): void {
        if (node.initializer) {
            this.visit(node.initializer as any)
        }
        if (node.condition) {
            this.visit(node.condition)
        }
        if (node.increment) {
            this.visit(node.increment)
        }
        this.visit(node.body)
    }

    visit_for_in_statement(node: ast.ForInStatement): void {
        this.visit(node.expr)
        this.visit(node.body)
    }

    visit_expr_statement(node: ast.ExprStatement): void {
        if (node.expr) {
            this.visit(node.expr)
        }
    }

    visit_return_statement(node: ast.ReturnStatement): void {
        if (node.expr) {
            this.visit(node.expr)
        }
    }

    visit_throw_statement(node: ast.ThrowStatement): void {
        this.visit(node.expr)
    }

    visit_try_catch_statement(node: ast.TryCatchStatement): void {
        this.visit(node.try_stmt)
        for (const catchClause of node.catches) {
            this.visit(catchClause[2])
        }
        if (node.finally_stmt) {
            this.visit(node.finally_stmt)
        }
    }

    visit_function(node: ast.Function): void {
        this.visit(node.body)
    }

    visit_variable_declaration(node: ast.VariableDeclaration): void {
        if (node.expr) {
            this.visit(node.expr)
        }
    }

    visit_variable_assignment(node: ast.VariableAssignment): void {
        this.visit(node.left)
        this.visit(node.right)
    }
}

// ====================================
// CloningVisitor
// ====================================

/**
 * Visitor that traverses and clones the AST tree
 */
export class CloningVisitor extends Visitor<ast.AST> {
    constructor(
        private clearTypes: boolean = true,
        private clearLocations: boolean = false,
        private inlineSubqueryFieldNames: boolean = false
    ) {
        super()
    }

    private getStart(node: ast.AST): ast.Position | undefined {
        return this.clearLocations ? undefined : node.start
    }

    private getEnd(node: ast.AST): ast.Position | undefined {
        return this.clearLocations ? undefined : node.end
    }

    private getType<T extends ast.Expr>(node: T): ast.Type | undefined {
        return this.clearTypes ? undefined : node.type
    }

    visit_cte(node: ast.CTE): ast.CTE {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            name: node.name,
            expr: this.visit(node.expr) as ast.SelectQuery | ast.SelectSetQuery,
            cte_type: node.cte_type,
        }
    }

    visit_alias(node: ast.Alias): ast.Alias {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            alias: node.alias,
            hidden: node.hidden,
            expr: this.visit(node.expr) as ast.Expr,
            from_asterisk: node.from_asterisk,
        }
    }

    visit_arithmetic_operation(node: ast.ArithmeticOperation): ast.ArithmeticOperation {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            left: this.visit(node.left) as ast.Expr,
            right: this.visit(node.right) as ast.Expr,
            op: node.op,
        }
    }

    visit_and(node: ast.And): ast.And {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            exprs: node.exprs.map((expr) => this.visit(expr) as ast.Expr),
        }
    }

    visit_or(node: ast.Or): ast.Or {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            exprs: node.exprs.map((expr) => this.visit(expr) as ast.Expr),
        }
    }

    visit_compare_operation(node: ast.CompareOperation): ast.CompareOperation {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            left: this.visit(node.left) as ast.Expr,
            right: this.visit(node.right) as ast.Expr,
            op: node.op,
        }
    }

    visit_not(node: ast.Not): ast.Not {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            expr: this.visit(node.expr) as ast.Expr,
        }
    }

    visit_between_expr(node: ast.BetweenExpr): ast.BetweenExpr {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            expr: this.visit(node.expr) as ast.Expr,
            low: this.visit(node.low) as ast.Expr,
            high: this.visit(node.high) as ast.Expr,
            negated: node.negated,
        }
    }

    visit_order_expr(node: ast.OrderExpr): ast.OrderExpr {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            expr: this.visit(node.expr) as ast.Expr,
            order: node.order,
        }
    }

    visit_tuple_access(node: ast.TupleAccess): ast.TupleAccess {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            tuple: this.visit(node.tuple) as ast.Expr,
            index: node.index,
            nullish: node.nullish,
        }
    }

    visit_tuple(node: ast.Tuple): ast.Tuple {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            exprs: node.exprs.map((expr) => this.visit(expr) as ast.Expr),
        }
    }

    visit_lambda(node: ast.Lambda): ast.Lambda {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            args: [...node.args],
            expr: this.visit(node.expr) as ast.Expr | ast.Block,
        }
    }

    visit_array_access(node: ast.ArrayAccess): ast.ArrayAccess {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            array: this.visit(node.array) as ast.Expr,
            property: this.visit(node.property) as ast.Expr,
            nullish: node.nullish,
        }
    }

    visit_array(node: ast.Array): ast.Array {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            exprs: node.exprs.map((expr) => this.visit(expr) as ast.Expr),
        }
    }

    visit_dict(node: ast.Dict): ast.Dict {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            items: node.items.map(([key, value]) => [this.visit(key) as ast.Expr, this.visit(value) as ast.Expr]) as [
                [ast.Expr, ast.Expr],
            ],
        }
    }

    visit_constant(node: ast.Constant): ast.Constant {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            value: node.value,
        }
    }

    visit_field(node: ast.Field): ast.Field {
        const field: ast.Field = {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            chain: [...node.chain],
            from_asterisk: node.from_asterisk,
        }

        // Handle inline subquery field names
        if (
            this.inlineSubqueryFieldNames &&
            node.type &&
            'joined_subquery' in node.type &&
            (node.type as any).joined_subquery != null &&
            (node.type as any).joined_subquery_field_name != null
        ) {
            field.chain = [(node.type as any).joined_subquery_field_name]
        }

        return field
    }

    visit_placeholder(node: ast.Placeholder): ast.Placeholder {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            expr: this.visit(node.expr) as ast.Expr,
            chain: node.chain,
            field: node.field,
        }
    }

    visit_call(node: ast.Call): ast.Call {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            name: node.name,
            args: node.args.map((arg) => this.visit(arg) as ast.Expr),
            params: node.params ? node.params.map((param) => this.visit(param) as ast.Expr) : undefined,
            distinct: node.distinct,
        }
    }

    visit_expr_call(node: ast.ExprCall): ast.ExprCall {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            expr: this.visit(node.expr) as ast.Expr,
            args: node.args.map((arg) => this.visit(arg) as ast.Expr),
        }
    }

    visit_ratio_expr(node: ast.RatioExpr): ast.RatioExpr {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            left: this.visit(node.left) as ast.Constant,
            right: node.right ? (this.visit(node.right) as ast.Constant) : undefined,
        }
    }

    visit_sample_expr(node: ast.SampleExpr): ast.SampleExpr {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            sample_value: this.visit(node.sample_value) as ast.RatioExpr,
            offset_value: node.offset_value ? (this.visit(node.offset_value) as ast.RatioExpr) : undefined,
        }
    }

    visit_join_expr(node: ast.JoinExpr): ast.JoinExpr {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node) as ast.TableOrSelectType | undefined,
            table: node.table ? (this.visit(node.table as any) as any) : undefined,
            table_args: node.table_args ? node.table_args.map((arg) => this.visit(arg) as ast.Expr) : undefined,
            next_join: node.next_join ? (this.visit(node.next_join) as ast.JoinExpr) : undefined,
            table_final: node.table_final,
            alias: node.alias,
            join_type: node.join_type,
            constraint: node.constraint ? (this.visit(node.constraint) as ast.JoinConstraint) : undefined,
            sample: node.sample ? (this.visit(node.sample) as ast.SampleExpr) : undefined,
        }
    }

    visit_select_query(node: ast.SelectQuery): ast.SelectQuery {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node) as ast.SelectQueryType | undefined,
            ctes: node.ctes
                ? Object.fromEntries(Object.entries(node.ctes).map(([key, cte]) => [key, this.visit(cte) as ast.CTE]))
                : undefined,
            select_from: node.select_from ? (this.visit(node.select_from) as ast.JoinExpr) : undefined,
            select: node.select.map((expr) => this.visit(expr) as ast.Expr),
            array_join_op: node.array_join_op,
            array_join_list: node.array_join_list
                ? node.array_join_list.map((expr) => this.visit(expr) as ast.Expr)
                : undefined,
            where: node.where ? (this.visit(node.where) as ast.Expr) : undefined,
            prewhere: node.prewhere ? (this.visit(node.prewhere) as ast.Expr) : undefined,
            having: node.having ? (this.visit(node.having) as ast.Expr) : undefined,
            group_by: node.group_by ? node.group_by.map((expr) => this.visit(expr) as ast.Expr) : undefined,
            order_by: node.order_by ? node.order_by.map((expr) => this.visit(expr) as ast.OrderExpr) : undefined,
            limit_by: node.limit_by ? (this.visit(node.limit_by) as ast.LimitByExpr) : undefined,
            limit: node.limit ? (this.visit(node.limit) as ast.Expr) : undefined,
            limit_with_ties: node.limit_with_ties,
            offset: node.offset ? (this.visit(node.offset) as ast.Expr) : undefined,
            distinct: node.distinct,
            window_exprs: node.window_exprs
                ? Object.fromEntries(
                      Object.entries(node.window_exprs).map(([name, expr]) => [
                          name,
                          this.visit(expr) as ast.WindowExpr,
                      ])
                  )
                : undefined,
            settings: node.settings ? { ...node.settings } : undefined,
            view_name: node.view_name,
        }
    }

    visit_select_set_query(node: ast.SelectSetQuery): ast.SelectSetQuery {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node) as ast.SelectSetQueryType | undefined,
            initial_select_query: this.visit(node.initial_select_query as any) as ast.SelectQuery | ast.SelectSetQuery,
            subsequent_select_queries: node.subsequent_select_queries.map((subsequent) => ({
                start: this.getStart(subsequent),
                end: this.getEnd(subsequent),
                set_operator: subsequent.set_operator,
                select_query: this.visit(subsequent.select_query as any) as ast.SelectQuery | ast.SelectSetQuery,
            })),
        }
    }

    visit_select_set_node(node: ast.SelectSetNode): ast.SelectSetNode {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            set_operator: node.set_operator,
            select_query: this.visit(node.select_query as any) as ast.SelectQuery | ast.SelectSetQuery,
        }
    }

    visit_window_expr(node: ast.WindowExpr): ast.WindowExpr {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            partition_by: node.partition_by ? node.partition_by.map((expr) => this.visit(expr) as ast.Expr) : undefined,
            order_by: node.order_by ? node.order_by.map((expr) => this.visit(expr) as ast.OrderExpr) : undefined,
            frame_method: node.frame_method,
            frame_start: node.frame_start ? (this.visit(node.frame_start) as ast.WindowFrameExpr) : undefined,
            frame_end: node.frame_end ? (this.visit(node.frame_end) as ast.WindowFrameExpr) : undefined,
        }
    }

    visit_window_function(node: ast.WindowFunction): ast.WindowFunction {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            name: node.name,
            exprs: node.exprs ? node.exprs.map((expr) => this.visit(expr) as ast.Expr) : undefined,
            args: node.args ? node.args.map((arg) => this.visit(arg) as ast.Expr) : undefined,
            over_expr: node.over_expr ? (this.visit(node.over_expr) as ast.WindowExpr) : undefined,
            over_identifier: node.over_identifier,
        }
    }

    visit_window_frame_expr(node: ast.WindowFrameExpr): ast.WindowFrameExpr {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            frame_type: node.frame_type,
            frame_value: node.frame_value,
        }
    }

    visit_join_constraint(node: ast.JoinConstraint): ast.JoinConstraint {
        return {
            expr: this.visit(node.expr) as ast.Expr,
            constraint_type: node.constraint_type,
        }
    }

    visit_hogqlx_tag(node: ast.HogQLXTag): ast.HogQLXTag {
        return {
            kind: node.kind,
            attributes: node.attributes.map((attr) => this.visit(attr) as ast.HogQLXAttribute),
        }
    }

    visit_hogqlx_attribute(node: ast.HogQLXAttribute): ast.HogQLXAttribute {
        if (Array.isArray(node.value)) {
            return {
                name: node.name,
                value: node.value.map((v) =>
                    isSimpleValue(v) ? this.visit({ value: v } as ast.Constant) : this.visit(v)
                ),
            }
        }

        let value = node.value
        if (isSimpleValue(value)) {
            value = { value } as ast.Constant
        }
        return {
            name: node.name,
            value: this.visit(value as any),
        }
    }

    visit_program(node: ast.Program): ast.Program {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            declarations: node.declarations.map((decl) => this.visit(decl) as ast.Declaration),
        }
    }

    visit_block(node: ast.Block): ast.Block {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            declarations: node.declarations.map((decl) => this.visit(decl) as ast.Declaration),
        }
    }

    visit_if_statement(node: ast.IfStatement): ast.IfStatement {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            expr: this.visit(node.expr) as ast.Expr,
            // oxlint-disable-next-line no-thenable
            then: this.visit(node.then) as ast.Statement,
            else_: node.else_ ? (this.visit(node.else_) as ast.Statement) : undefined,
        }
    }

    visit_while_statement(node: ast.WhileStatement): ast.WhileStatement {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            expr: this.visit(node.expr) as ast.Expr,
            body: this.visit(node.body) as ast.Statement,
        }
    }

    visit_for_statement(node: ast.ForStatement): ast.ForStatement {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            initializer: node.initializer ? (this.visit(node.initializer as any) as any) : undefined,
            condition: node.condition ? (this.visit(node.condition) as ast.Expr) : undefined,
            increment: node.increment ? (this.visit(node.increment) as ast.Expr) : undefined,
            body: this.visit(node.body) as ast.Statement,
        }
    }

    visit_for_in_statement(node: ast.ForInStatement): ast.ForInStatement {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            valueVar: node.valueVar,
            keyVar: node.keyVar,
            expr: this.visit(node.expr) as ast.Expr,
            body: this.visit(node.body) as ast.Statement,
        }
    }

    visit_expr_statement(node: ast.ExprStatement): ast.ExprStatement {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            expr: node.expr ? (this.visit(node.expr) as ast.Expr) : undefined,
        }
    }

    visit_return_statement(node: ast.ReturnStatement): ast.ReturnStatement {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            expr: node.expr ? (this.visit(node.expr) as ast.Expr) : undefined,
        }
    }

    visit_throw_statement(node: ast.ThrowStatement): ast.ThrowStatement {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            expr: this.visit(node.expr) as ast.Expr,
        }
    }

    visit_try_catch_statement(node: ast.TryCatchStatement): ast.TryCatchStatement {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            try_stmt: this.visit(node.try_stmt) as ast.Statement,
            catches: node.catches.map(
                ([type, name, stmt]) =>
                    [type, name, this.visit(stmt) as ast.Statement] as [string | null, string | null, ast.Statement]
            ) as [[string | null, string | null, ast.Statement]],
            finally_stmt: node.finally_stmt ? (this.visit(node.finally_stmt) as ast.Statement) : undefined,
        }
    }

    visit_function(node: ast.Function): ast.Function {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            name: node.name,
            params: [...node.params],
            body: this.visit(node.body) as ast.Statement,
        }
    }

    visit_variable_declaration(node: ast.VariableDeclaration): ast.VariableDeclaration {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            name: node.name,
            expr: node.expr ? (this.visit(node.expr) as ast.Expr) : undefined,
        }
    }

    visit_variable_assignment(node: ast.VariableAssignment): ast.VariableAssignment {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            left: this.visit(node.left) as ast.Expr,
            right: this.visit(node.right) as ast.Expr,
        }
    }

    visit_limit_by_expr(node: ast.LimitByExpr): ast.LimitByExpr {
        return {
            start: this.getStart(node),
            end: this.getEnd(node),
            type: this.getType(node),
            n: this.visit(node.n) as ast.Expr,
            offset_value: node.offset_value ? (this.visit(node.offset_value) as ast.Expr) : undefined,
            exprs: node.exprs.map((expr) => this.visit(expr) as ast.Expr),
        }
    }

    // Type visitor methods - these typically don't need to clone deeply
    visit_lambda_argument_type(node: ast.LambdaArgumentType): ast.LambdaArgumentType {
        return { ...node }
    }

    visit_field_alias_type(node: ast.FieldAliasType): ast.FieldAliasType {
        return {
            ...node,
            type: this.visit(node.type) as ast.Type,
        }
    }

    visit_field_type(node: ast.FieldType): ast.FieldType {
        return { ...node }
    }

    visit_select_query_type(node: ast.SelectQueryType): ast.SelectQueryType {
        return { ...node }
    }

    visit_select_set_query_type(node: ast.SelectSetQueryType): ast.SelectSetQueryType {
        return { ...node }
    }

    visit_table_type(node: ast.TableType): ast.TableType {
        return { ...node }
    }

    visit_lazy_table_type(node: ast.LazyTableType): ast.LazyTableType {
        return { ...node }
    }

    visit_field_traverser_type(node: ast.FieldTraverserType): ast.FieldTraverserType {
        return { ...node }
    }

    visit_lazy_join_type(node: ast.LazyJoinType): ast.LazyJoinType {
        return { ...node }
    }

    visit_virtual_table_type(node: ast.VirtualTableType): ast.VirtualTableType {
        return { ...node }
    }

    visit_table_alias_type(node: ast.TableAliasType): ast.TableAliasType {
        return { ...node }
    }

    visit_select_query_alias_type(node: ast.SelectQueryAliasType): ast.SelectQueryAliasType {
        return { ...node }
    }

    visit_select_view_type(node: ast.SelectViewType): ast.SelectViewType {
        return { ...node }
    }

    visit_asterisk_type(node: ast.AsteriskType): ast.AsteriskType {
        return { ...node }
    }

    visit_call_type(node: ast.CallType): ast.CallType {
        return { ...node }
    }

    visit_integer_type(node: ast.IntegerType): ast.IntegerType {
        return { ...node }
    }

    visit_float_type(node: ast.FloatType): ast.FloatType {
        return { ...node }
    }

    visit_decimal_type(node: ast.DecimalType): ast.DecimalType {
        return { ...node }
    }

    visit_string_type(node: ast.StringType): ast.StringType {
        return { ...node }
    }

    visit_string_json_type(node: ast.StringJSONType): ast.StringJSONType {
        return { ...node }
    }

    visit_string_array_type(node: ast.StringArrayType): ast.StringArrayType {
        return { ...node }
    }

    visit_boolean_type(node: ast.BooleanType): ast.BooleanType {
        return { ...node }
    }

    visit_unknown_type(node: ast.UnknownType): ast.UnknownType {
        return { ...node }
    }

    visit_array_type(node: ast.ArrayType): ast.ArrayType {
        return {
            ...node,
            item_type: this.visit(node.item_type) as ast.ConstantType,
        }
    }

    visit_tuple_type(node: ast.TupleType): ast.TupleType {
        return {
            ...node,
            item_types: node.item_types.map((t) => this.visit(t) as ast.ConstantType),
        }
    }

    visit_date_type(node: ast.DateType): ast.DateType {
        return { ...node }
    }

    visit_date_time_type(node: ast.DateTimeType): ast.DateTimeType {
        return { ...node }
    }

    visit_interval_type(node: ast.IntervalType): ast.IntervalType {
        return { ...node }
    }

    visit_uuid_type(node: ast.UUIDType): ast.UUIDType {
        return { ...node }
    }

    visit_property_type(node: ast.PropertyType): ast.PropertyType {
        return { ...node }
    }

    visit_expression_field_type(node: ast.ExpressionFieldType): ast.ExpressionFieldType {
        return { ...node }
    }

    visit_unresolved_field_type(node: ast.UnresolvedFieldType): ast.UnresolvedFieldType {
        return { ...node }
    }
}
