/**
 * HogQL AST TypeScript Definitions
 *
 * These interfaces represent the Abstract Syntax Tree for HogQL queries.
 * They mirror the Python dataclass definitions for consistent parsing between backend and frontend.
 */

// ====================================
// Base Types
// ====================================

export interface Position {
    line: number
    column: number
    offset: number
}

export interface AST {
    start?: Position
    end?: Position
}

// ====================================
// Constants and Enums
// ====================================

export type ConstantDataType =
    | 'int'
    | 'float'
    | 'str'
    | 'bool'
    | 'date'
    | 'datetime'
    | 'uuid'
    | 'array'
    | 'tuple'
    | 'unknown'

export type ArithmeticOperationOp = '+' | '-' | '*' | '/' | '%'

export type CompareOperationOp =
    | '=='
    | '!='
    | '>'
    | '>='
    | '<'
    | '<='
    | 'like'
    | 'ilike'
    | 'not like'
    | 'not ilike'
    | 'in'
    | 'global in'
    | 'not in'
    | 'global not in'
    | 'in cohort'
    | 'not in cohort'
    | '=~'
    | '=~*'
    | '!~'
    | '!~*'

export type SetOperator = 'UNION ALL' | 'UNION DISTINCT' | 'INTERSECT' | 'INTERSECT DISTINCT' | 'EXCEPT'

export type WindowFrameType = 'CURRENT ROW' | 'PRECEDING' | 'FOLLOWING'
export type WindowFrameMethod = 'ROWS' | 'RANGE'
export type JoinConstraintType = 'ON' | 'USING'
export type OrderDirection = 'ASC' | 'DESC'

// ====================================
// Type System
// ====================================

export interface Type extends AST {}

export interface ConstantType extends Type {
    data_type: ConstantDataType
    nullable?: boolean
}

export interface UnknownType extends ConstantType {
    data_type: 'unknown'
}

export interface IntegerType extends ConstantType {
    data_type: 'int'
}

export interface DecimalType extends ConstantType {
    data_type: 'unknown'
}

export interface FloatType extends ConstantType {
    data_type: 'float'
}

export interface StringType extends ConstantType {
    data_type: 'str'
}

export interface StringJSONType extends StringType {}

export interface StringArrayType extends StringType {}

export interface BooleanType extends ConstantType {
    data_type: 'bool'
}

export interface DateType extends ConstantType {
    data_type: 'date'
}

export interface DateTimeType extends ConstantType {
    data_type: 'datetime'
}

export interface IntervalType extends ConstantType {
    data_type: 'unknown'
}

export interface UUIDType extends ConstantType {
    data_type: 'uuid'
}

export interface ArrayType extends ConstantType {
    data_type: 'array'
    item_type: ConstantType
}

export interface TupleType extends ConstantType {
    data_type: 'tuple'
    item_types: ConstantType[]
    repeat?: boolean
}

export interface CallType extends Type {
    name: string
    arg_types: ConstantType[]
    param_types?: ConstantType[]
    return_type: ConstantType
}

export interface FieldAliasType extends Type {
    alias: string
    type: Type
}

export interface SelectQueryType extends Type {
    aliases: Record<string, FieldAliasType>
    columns: Record<string, Type>
    tables: Record<string, TableOrSelectType>
    ctes: Record<string, CTE>
    anonymous_tables: (SelectQueryType | SelectSetQueryType)[]
    parent?: SelectQueryType | SelectSetQueryType
    is_lambda_type?: boolean
}

export interface SelectSetQueryType extends Type {
    types: (SelectQueryType | SelectSetQueryType)[]
}

export interface SelectQueryAliasType extends Type {
    alias: string
    select_query_type: SelectQueryType | SelectSetQueryType
}

export interface BaseTableType extends Type {}

export interface TableType extends BaseTableType {
    table: any // Would be Table from database.models
}

export interface LazyJoinType extends BaseTableType {
    table_type: TableOrSelectType
    field: string
    lazy_join: any // Would be LazyJoin from database.models
}

export interface LazyTableType extends BaseTableType {
    table: any // Would be LazyTable from database.models
}

export interface TableAliasType extends BaseTableType {
    alias: string
    table_type: TableType | LazyTableType
}

export interface VirtualTableType extends BaseTableType {
    table_type: TableOrSelectType
    field: string
    virtual_table: any // Would be VirtualTable from database.models
}

export interface SelectViewType extends BaseTableType {
    view_name: string
    alias: string
    select_query_type: SelectQueryType | SelectSetQueryType
}

export interface AsteriskType extends Type {
    table_type: TableOrSelectType
}

export interface FieldTraverserType extends Type {
    chain: (string | number)[]
    table_type: TableOrSelectType
}

export interface ExpressionFieldType extends Type {
    name: string
    expr: Expr
    table_type: TableOrSelectType
    isolate_scope?: boolean
}

export interface FieldType extends Type {
    name: string
    table_type: TableOrSelectType
}

export interface UnresolvedFieldType extends Type {
    name: string
}

export interface PropertyType extends Type {
    chain: (string | number)[]
    field_type: FieldType
    joined_subquery?: SelectQueryAliasType
    joined_subquery_field_name?: string
}

export interface LambdaArgumentType extends Type {
    name: string
}

export type TableOrSelectType = BaseTableType | SelectSetQueryType | SelectQueryType | SelectQueryAliasType

// ====================================
// Expressions
// ====================================

export interface Expr extends AST {
    type?: Type
}

export interface CTE extends AST {
    name: string
    expr: SelectQuery | SelectSetQuery
    cte_type?: 'CTE' | 'WINDOW'
}

// Declarations and Statements

export interface Declaration extends AST {}

export interface VariableAssignment extends Declaration {
    left: Expr
    right: Expr
}

export interface VariableDeclaration extends Declaration {
    name: string
    expr?: Expr
}

export interface Statement extends Declaration {}

export interface ExprStatement extends Statement {
    expr?: Expr
}

export interface ReturnStatement extends Statement {
    expr?: Expr
}

export interface ThrowStatement extends Statement {
    expr: Expr
}

export interface TryCatchStatement extends Statement {
    try_stmt: Statement
    catches: [string | null, string | null, Statement][]
    finally_stmt?: Statement
}

export interface IfStatement extends Statement {
    expr: Expr
    then: Statement
    else_?: Statement
}

export interface WhileStatement extends Statement {
    expr: Expr
    body: Statement
}

export interface ForStatement extends Statement {
    initializer?: VariableDeclaration | VariableAssignment | Expr
    condition?: Expr
    increment?: Expr
    body: Statement
}

export interface ForInStatement extends Statement {
    keyVar?: string
    valueVar: string
    expr: Expr
    body: Statement
}

export interface Function extends Statement {
    name: string
    params: string[]
    body: Statement
}

export interface Block extends Statement {
    declarations: Declaration[]
}

export interface Program extends AST {
    declarations: Declaration[]
}

// Core Expressions

export interface Alias extends Expr {
    alias: string
    expr: Expr
    hidden?: boolean
    from_asterisk?: boolean
}

export interface ArithmeticOperation extends Expr {
    left: Expr
    right: Expr
    op: ArithmeticOperationOp
}

export interface And extends Expr {
    exprs: Expr[]
}

export interface Or extends Expr {
    exprs: Expr[]
}

export interface CompareOperation extends Expr {
    left: Expr
    right: Expr
    op: CompareOperationOp
}

export interface Not extends Expr {
    expr: Expr
}

export interface BetweenExpr extends Expr {
    expr: Expr
    low: Expr
    high: Expr
    negated?: boolean
}

export interface OrderExpr extends Expr {
    expr: Expr
    order?: OrderDirection
}

export interface ArrayAccess extends Expr {
    array: Expr
    property: Expr
    nullish?: boolean
}

export interface Array extends Expr {
    exprs: Expr[]
}

export interface Dict extends Expr {
    items: [Expr, Expr][]
}

export interface TupleAccess extends Expr {
    tuple: Expr
    index: number
    nullish?: boolean
}

export interface Tuple extends Expr {
    exprs: Expr[]
}

export interface Lambda extends Expr {
    args: string[]
    expr: Expr | Block
}

export interface Constant extends Expr {
    value: any
}

export interface Field extends Expr {
    chain: (string | number)[]
    from_asterisk?: boolean
}

export interface Placeholder extends Expr {
    expr: Expr
    chain?: (string | number)[]
    field?: string
}

export interface Call extends Expr {
    name: string
    args: Expr[]
    params?: Expr[]
    distinct?: boolean
}

export interface ExprCall extends Expr {
    expr: Expr
    args: Expr[]
}

// Query Components

export interface JoinConstraint extends Expr {
    expr: Expr
    constraint_type: JoinConstraintType
}

export interface JoinExpr extends Expr {
    type?: TableOrSelectType
    join_type?: string
    table?: SelectQuery | SelectSetQuery | Placeholder | HogQLXTag | Field
    table_args?: Expr[]
    alias?: string
    table_final?: boolean
    constraint?: JoinConstraint
    next_join?: JoinExpr
    sample?: SampleExpr
}

export interface WindowFrameExpr extends Expr {
    frame_type?: WindowFrameType
    frame_value?: number
}

export interface WindowExpr extends Expr {
    partition_by?: Expr[]
    order_by?: OrderExpr[]
    frame_method?: WindowFrameMethod
    frame_start?: WindowFrameExpr
    frame_end?: WindowFrameExpr
}

export interface WindowFunction extends Expr {
    name: string
    args?: Expr[]
    exprs?: Expr[]
    over_expr?: WindowExpr
    over_identifier?: string
}

export interface LimitByExpr extends Expr {
    n: Expr
    exprs: Expr[]
    offset_value?: Expr
}

export interface SelectQuery extends Expr {
    type?: SelectQueryType
    ctes?: Record<string, CTE>
    select: Expr[]
    distinct?: boolean
    select_from?: JoinExpr
    array_join_op?: string
    array_join_list?: Expr[]
    window_exprs?: Record<string, WindowExpr>
    where?: Expr
    prewhere?: Expr
    having?: Expr
    group_by?: Expr[]
    order_by?: OrderExpr[]
    limit?: Expr
    limit_by?: LimitByExpr
    limit_with_ties?: boolean
    offset?: Expr
    settings?: any // Would be HogQLQuerySettings
    view_name?: string
}

export interface SelectSetNode extends AST {
    select_query: SelectQuery | SelectSetQuery
    set_operator: SetOperator
}

export interface SelectSetQuery extends Expr {
    type?: SelectSetQueryType
    initial_select_query: SelectQuery | SelectSetQuery
    subsequent_select_queries: SelectSetNode[]
}

export interface RatioExpr extends Expr {
    left: Constant
    right?: Constant
}

export interface SampleExpr extends Expr {
    sample_value: RatioExpr
    offset_value?: RatioExpr
}

export interface HogQLXAttribute extends AST {
    name: string
    value: any
}

export interface HogQLXTag extends Expr {
    kind: string
    attributes: HogQLXAttribute[]
}

// ====================================
// Type Guards
// ====================================

export function isSelectQuery(node: any): node is SelectQuery {
    return node && 'select' in node && Array.isArray(node.select)
}

export function isField(node: any): node is Field {
    return node && 'chain' in node && Array.isArray(node.chain)
}

export function isConstant(node: any): node is Constant {
    return node && 'value' in node
}

export function isCall(node: any): node is Call {
    return node && 'name' in node && 'args' in node && typeof node.name === 'string'
}

export function isAlias(node: any): node is Alias {
    return node && 'alias' in node && 'expr' in node && typeof node.alias === 'string'
}

export function isCompareOperation(node: any): node is CompareOperation {
    return node && 'left' in node && 'right' in node && 'op' in node
}

export function isArithmeticOperation(node: any): node is ArithmeticOperation {
    return node && 'left' in node && 'right' in node && 'op' in node && ['+', '-', '*', '/', '%'].includes(node.op)
}

export function isAnd(node: any): node is And {
    return node && 'exprs' in node && Array.isArray(node.exprs)
}

export function isOr(node: any): node is Or {
    return node && 'exprs' in node && Array.isArray(node.exprs)
}

export function isProgram(node: any): node is Program {
    return node && 'declarations' in node && Array.isArray(node.declarations)
}
