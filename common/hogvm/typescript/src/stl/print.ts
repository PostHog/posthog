import { isHogAST, isHogCallable, isHogClosure, isHogDate, isHogDateTime, isHogError } from '../objects'
import { convertJSToHog } from '../utils'

const escapeCharsMap: Record<string, string> = {
    '\b': '\\b',
    '\f': '\\f',
    '\r': '\\r',
    '\n': '\\n',
    '\t': '\\t',
    '\0': '\\0',
    '\v': '\\v',
    '\\': '\\\\',
}

const singlequoteEscapeCharsMap: Record<string, string> = {
    ...escapeCharsMap,
    "'": "\\'",
}

const backquoteEscapeCharsMap: Record<string, string> = {
    ...escapeCharsMap,
    '`': '\\`',
}

export function escapeString(value: string): string {
    return `'${value
        .split('')
        .map((c) => singlequoteEscapeCharsMap[c] || c)
        .join('')}'`
}

export function escapeIdentifier(identifier: string | number): string {
    if (typeof identifier === 'number') {
        return identifier.toString()
    }
    if (/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(identifier)) {
        return identifier
    }
    return `\`${identifier
        .split('')
        .map((c) => backquoteEscapeCharsMap[c] || c)
        .join('')}\``
}

export function printHogValue(obj: any, marked: Set<any> | undefined = undefined): string {
    if (!marked) {
        marked = new Set()
    }
    if (typeof obj === 'object' && obj !== null && obj !== undefined) {
        if (
            marked.has(obj) &&
            !isHogDateTime(obj) &&
            !isHogDate(obj) &&
            !isHogError(obj) &&
            !isHogClosure(obj) &&
            !isHogCallable(obj) &&
            !isHogAST(obj)
        ) {
            return 'null'
        }
        marked.add(obj)
        try {
            if (Array.isArray(obj)) {
                if ((obj as any).__isHogTuple) {
                    if (obj.length < 2) {
                        return `tuple(${obj.map((o) => printHogValue(o, marked)).join(', ')})`
                    }
                    return `(${obj.map((o) => printHogValue(o, marked)).join(', ')})`
                }
                return `[${obj.map((o) => printHogValue(o, marked)).join(', ')}]`
            }
            if (isHogDateTime(obj)) {
                const millis = String(obj.dt)
                return `DateTime(${millis}${millis.includes('.') ? '' : '.0'}, ${escapeString(obj.zone)})`
            }
            if (isHogDate(obj)) {
                return `Date(${obj.year}, ${obj.month}, ${obj.day})`
            }
            if (isHogError(obj)) {
                return `${String(obj.type)}(${escapeString(obj.message)}${
                    obj.payload ? `, ${printHogValue(obj.payload, marked)}` : ''
                })`
            }
            if (isHogClosure(obj)) {
                return printHogValue(obj.callable, marked)
            }
            if (isHogCallable(obj)) {
                return `fn<${escapeIdentifier(obj.name ?? 'lambda')}(${printHogValue(obj.argCount)})>`
            }
            if (isHogAST(obj)) {
                return `sql(${new HogQLPrinter(false, marked).print(obj)})`
            }
            if (obj instanceof Map) {
                return `{${Array.from(obj.entries())
                    .map(([key, value]) => `${printHogValue(key, marked)}: ${printHogValue(value, marked)}`)
                    .join(', ')}}`
            }
            return `{${Object.entries(obj)
                .map(([key, value]) => `${printHogValue(key, marked)}: ${printHogValue(value, marked)}`)
                .join(', ')}}`
        } finally {
            marked.delete(obj)
        }
    } else if (typeof obj === 'boolean') {
        return obj ? 'true' : 'false'
    } else if (obj === null || obj === undefined) {
        return 'null'
    } else if (typeof obj === 'string') {
        return escapeString(obj)
    }
    return obj.toString()
}

export function printHogStringOutput(obj: any): string {
    if (typeof obj === 'string') {
        return obj
    }
    return printHogValue(obj)
}

type ASTNode = Map<string, any> | null

// Note: this printer currently is experimental and used for debugging/printing SQL only.
// When making queries via run(query), we send the AST nodes directly to the server.
export class HogQLPrinter {
    private stack: ASTNode[] = []
    private indentLevel: number = -1
    private tabSize: number = 4
    private pretty: boolean
    private marked: Set<any>

    constructor(pretty: boolean = false, marked: Set<any> | undefined = undefined) {
        this.pretty = pretty
        this.marked = marked || new Set()
    }

    private indent(extra: number = 0): string {
        return ' '.repeat(this.tabSize * (this.indentLevel + extra))
    }

    public print(node: ASTNode): string {
        return this.visit(node)
    }

    private visit(node: ASTNode): string {
        if (!node) {
            return ''
        }
        if (!(node instanceof Map)) {
            if (isHogAST(node)) {
                node = convertJSToHog(node)
            } else {
                return this.escapeValue(node)
            }
        }

        this.stack.push(node)
        this.indentLevel += 1

        let result: string
        const nodeType = node?.get('__hx_ast') as string | undefined

        if (!nodeType) {
            throw new Error('Node type is missing or undefined.')
        }

        switch (nodeType) {
            case 'SelectQuery':
                result = this.visitSelectQuery(node)
                break
            case 'SelectSetQuery':
                result = this.visitSelectSetQuery(node)
                break
            case 'Call':
                result = this.visitCall(node)
                break
            case 'Constant':
                result = this.visitConstant(node)
                break
            case 'Field':
                result = this.visitField(node)
                break
            case 'Alias':
                result = this.visitAlias(node)
                break
            case 'And':
                result = this.visitAnd(node)
                break
            case 'Or':
                result = this.visitOr(node)
                break
            case 'Not':
                result = this.visitNot(node)
                break
            case 'CompareOperation':
                result = this.visitCompareOperation(node)
                break
            case 'Tuple':
                result = this.visitTuple(node)
                break
            case 'Array':
                result = this.visitArray(node)
                break
            case 'Lambda':
                result = this.visitLambda(node)
                break
            case 'OrderExpr':
                result = this.visitOrderExpr(node)
                break
            case 'ArithmeticOperation':
                result = this.visitArithmeticOperation(node)
                break
            case 'Asterisk':
                result = this.visitAsterisk(node)
                break
            case 'JoinExpr':
                result = this.visitJoinExpr(node)
                break
            case 'JoinConstraint':
                result = this.visitJoinConstraint(node)
                break
            case 'WindowExpr':
                result = this.visitWindowExpr(node)
                break
            case 'WindowFunction':
                result = this.visitWindowFunction(node)
                break
            case 'WindowFrameExpr':
                result = this.visitWindowFrameExpr(node)
                break
            case 'SampleExpr':
                result = this.visitSampleExpr(node)
                break
            case 'RatioExpr':
                result = this.visitRatioExpr(node)
                break
            case 'HogQLXTag':
                result = this.visitHogQLXTag(node)
                break
            default:
                throw new Error(`Unknown AST node type: ${nodeType}`)
        }

        this.indentLevel -= 1
        this.stack.pop()

        return result
    }

    private visitSelectQuery(node: ASTNode): string {
        if (!node) {
            return ''
        }
        const isTopLevelQuery = this.stack.length <= 1

        const selectNodes = node.get('select') as ASTNode[] | undefined
        const selectExpressions = selectNodes ? selectNodes.map((expr) => this.visit(expr)) : []
        const space = this.pretty ? `\n${this.indent(1)}` : ' '
        const comma = this.pretty ? `,\n${this.indent(1)}` : ', '

        const clauses: string[] = [
            `SELECT${node.get('distinct') ? ' DISTINCT' : ''}${space}${selectExpressions.join(comma)}`,
        ]

        if (node.has('select_from')) {
            const fromExpr = this.visitJoinExpression(node.get('select_from'))
            if (fromExpr) {
                clauses.push(`FROM${space}${fromExpr}`)
            }
        }

        if (node.has('prewhere')) {
            const prewhereExpr = this.visit(node.get('prewhere'))
            if (prewhereExpr) {
                clauses.push(`PREWHERE${space}${prewhereExpr}`)
            }
        }

        if (node.has('where')) {
            const whereExpr = this.visit(node.get('where'))
            if (whereExpr) {
                clauses.push(`WHERE${space}${whereExpr}`)
            }
        }

        if (
            node.has('group_by') &&
            Array.isArray(node.get('group_by')) &&
            (node.get('group_by') as ASTNode[]).length > 0
        ) {
            const groupByExpressions = (node.get('group_by') as ASTNode[]).map((expr) => this.visit(expr))
            clauses.push(`GROUP BY${space}${groupByExpressions.join(comma)}`)
        }

        if (node.has('having')) {
            const havingExpr = this.visit(node.get('having'))
            if (havingExpr) {
                clauses.push(`HAVING${space}${havingExpr}`)
            }
        }

        if (
            node.has('order_by') &&
            Array.isArray(node.get('order_by')) &&
            (node.get('order_by') as ASTNode[]).length > 0
        ) {
            const orderByExpressions = (node.get('order_by') as ASTNode[]).map((expr) => this.visit(expr))
            clauses.push(`ORDER BY${space}${orderByExpressions.join(comma)}`)
        }

        if (node.has('limit')) {
            const limitExpr = this.visit(node.get('limit'))
            if (limitExpr) {
                clauses.push(`LIMIT ${limitExpr}`)
            }
            if (node.get('limit_with_ties')) {
                clauses.push('WITH TIES')
            }
            if (node.has('offset')) {
                const offsetExpr = this.visit(node.get('offset'))
                if (offsetExpr) {
                    clauses.push(`OFFSET ${offsetExpr}`)
                }
            }
        }

        if (node.has('window_exprs')) {
            const windowExprs = node.get('window_exprs') as Map<string, ASTNode> | undefined
            if (windowExprs) {
                const windowExpressions = Array.from(windowExprs.entries())
                    .map(([name, expr]) => `${escapeIdentifier(name)} AS (${this.visit(expr)})`)
                    .join(comma)
                if (windowExpressions) {
                    clauses.push(`WINDOW${space}${windowExpressions}`)
                }
            }
        }

        let response = this.pretty ? clauses.map((clause) => `${this.indent()}${clause}`).join('\n') : clauses.join(' ')

        if (!isTopLevelQuery) {
            response = `(${response})`
        }

        return response
    }

    private visitSelectSetQuery(node: ASTNode): string {
        if (!node) {
            return ''
        }
        this.indentLevel -= 1
        const initialSelectQuery = node.get('initial_select_query') as ASTNode
        let result = this.visit(initialSelectQuery)

        if (this.pretty) {
            result = result.trim()
        }

        const subsequentQueries = node.get('subsequent_select_queries') as {
            select_query: ASTNode
            set_operator: string
        }[]
        if (subsequentQueries) {
            for (const expr of subsequentQueries) {
                const query = this.visit(expr.select_query)
                const trimmedQuery = this.pretty ? query.trim() : query

                if (expr.set_operator) {
                    if (this.pretty) {
                        result += `\n${this.indent(1)}${expr.set_operator}\n${this.indent(1)}`
                    } else {
                        result += ` ${expr.set_operator} `
                    }
                }
                result += trimmedQuery
            }
        }
        this.indentLevel += 1

        if (this.stack.length > 1) {
            return `(${result.trim()})`
        }
        return result
    }

    // Helper method to handle join expressions in the FROM clause
    private visitJoinExpression(node: ASTNode): string {
        if (!node) {
            return ''
        }
        const nodeType = node.get('__hx_ast') as string

        if (nodeType === 'JoinExpr') {
            return this.visitJoinExpr(node)
        }
        // If it's not a JoinExpr, treat it as a regular table or subquery
        return this.visit(node)
    }

    private visitJoinExpr(node: ASTNode): string {
        if (!node) {
            return ''
        }
        const joinParts: string[] = []

        // Handle the initial table or subquery
        const initialTable = this.visit(node.get('table'))

        // Add alias if present
        if (node.has('alias') && node.get('alias') !== initialTable) {
            joinParts.push(`${initialTable} AS ${escapeIdentifier(node.get('alias'))}`)
        } else {
            joinParts.push(initialTable)
        }

        // Process the chain of joins via next_join
        let currentJoin = node.get('next_join') as ASTNode | undefined
        while (currentJoin) {
            const joinType = currentJoin.get('join_type') || 'JOIN'
            const table = this.visit(currentJoin.get('table'))
            const constraint = currentJoin.get('constraint') as ASTNode | undefined
            const constraintClause = constraint ? `${constraint.get('constraint_type')} ${this.visit(constraint)}` : ''

            // Add alias if present
            let tableWithAlias = table
            if (currentJoin.has('alias') && currentJoin.get('alias') !== table) {
                tableWithAlias = `${table} AS ${escapeIdentifier(currentJoin.get('alias'))}`
            }

            joinParts.push(`${joinType} ${tableWithAlias} ${constraintClause}`.trim())

            currentJoin = currentJoin.get('next_join') as ASTNode | undefined
        }

        return joinParts.join(' ')
    }

    private visitJoinConstraint(node: ASTNode): string {
        if (!node) {
            return ''
        }
        return this.visit(node.get('expr'))
    }

    private visitCall(node: ASTNode): string {
        if (!node) {
            return ''
        }
        const name = node.get('name') as string
        const args = (node.get('args') as ASTNode[])?.map((arg) => this.visit(arg)) || []
        return `${name}(${args.join(', ')})`
    }

    private visitConstant(node: ASTNode): string {
        if (!node) {
            return ''
        }
        const value = node.get('value')
        return this.escapeValue(value)
    }

    private visitField(node: ASTNode): string {
        if (!node) {
            return ''
        }
        const chain = node.get('chain') as Array<string | number>
        if (chain.length === 1 && chain[0] === '*') {
            return '*'
        }
        return chain.map((identifier) => this.escapeIdentifierOrIndex(identifier)).join('.')
    }

    private visitAlias(node: ASTNode): string {
        if (!node) {
            return ''
        }
        if (node.get('hidden')) {
            return this.visit(node.get('expr'))
        }
        let expr = node.get('expr') as ASTNode
        while (expr && expr instanceof Map && expr.get('__hx_ast') === 'Alias' && expr.get('hidden')) {
            expr = expr.get('expr')
        }
        const inside = this.visit(expr)
        const alias = escapeIdentifier(node.get('alias') as string)
        return `${inside} AS ${alias}`
    }

    private visitAnd(node: ASTNode): string {
        if (!node) {
            return ''
        }
        const exprs = node.get('exprs') as ASTNode[] | undefined
        if (!exprs || exprs.length === 0) {
            return ''
        }
        if (exprs.length === 1) {
            return this.visit(exprs[0])
        }
        const expressions = exprs.map((expr) => this.visit(expr))
        return `and(${expressions.join(', ')})`
    }

    private visitOr(node: ASTNode): string {
        if (!node) {
            return ''
        }
        const exprs = node.get('exprs') as ASTNode[] | undefined
        if (!exprs || exprs.length === 0) {
            return ''
        }
        if (exprs.length === 1) {
            return this.visit(exprs[0])
        }
        const expressions = exprs.map((expr) => this.visit(expr))
        return `or(${expressions.join(', ')})`
    }

    private visitNot(node: ASTNode): string {
        if (!node) {
            return ''
        }
        return `not(${this.visit(node.get('expr'))})`
    }

    private visitCompareOperation(node: ASTNode): string {
        if (!node) {
            return ''
        }
        const left = this.visit(node.get('left'))
        const right = this.visit(node.get('right'))
        const op = node.get('op') as string
        const opMap: { [key: string]: string } = {
            '==': 'equals',
            '!=': 'notEquals',
            '<': 'less',
            '>': 'greater',
            '<=': 'lessOrEquals',
            '>=': 'greaterOrEquals',
            in: 'in',
            'not in': 'notIn',
            like: 'like',
            'not like': 'notLike',
            ilike: 'ilike',
            'not ilike': 'notILike',
            '=~': 'match',
            '!~': 'match',
            '=~*': 'match',
            '!~*': 'match',
        }

        const functionName = opMap[op] || op
        if (op === '!~*') {
            return `not(${functionName}(${left}, concat('(?i)', ${right})))`
        }
        if (op === '=~*') {
            return `${functionName}(${left}, concat('(?i)', ${right}))`
        }
        if (op === '!~') {
            return `not(${functionName}(${left}, ${right}))`
        }
        return `${functionName}(${left}, ${right})`
    }

    private visitTuple(node: ASTNode): string {
        if (!node) {
            return ''
        }
        const exprs = node.get('exprs') as ASTNode[] | undefined
        if (!exprs) {
            return ''
        }
        const expressions = exprs.map((expr) => this.visit(expr))
        return `tuple(${expressions.join(', ')})`
    }

    private visitArray(node: ASTNode): string {
        if (!node) {
            return ''
        }
        const exprs = node.get('exprs') as ASTNode[] | undefined
        if (!exprs) {
            return ''
        }
        const expressions = exprs.map((expr) => this.visit(expr))
        return `[${expressions.join(', ')}]`
    }

    private visitLambda(node: ASTNode): string {
        if (!node) {
            return ''
        }
        const args = node.get('args') as string[] | undefined
        if (!args || args.length === 0) {
            throw new Error('Lambdas require at least one argument')
        }
        const escapedArgs = args.map((arg) => escapeIdentifier(arg))
        const argList = escapedArgs.length === 1 ? escapedArgs[0] : `(${escapedArgs.join(', ')})`
        return `${argList} -> ${this.visit(node.get('expr'))}`
    }

    private visitOrderExpr(node: ASTNode): string {
        if (!node) {
            return ''
        }
        return `${this.visit(node.get('expr'))} ${node.get('order')}`
    }

    private visitArithmeticOperation(node: ASTNode): string {
        if (!node) {
            return ''
        }
        const left = this.visit(node.get('left'))
        const right = this.visit(node.get('right'))
        const op = node.get('op') as string
        switch (op) {
            case '+':
                return `plus(${left}, ${right})`
            case '-':
                return `minus(${left}, ${right})`
            case '*':
                return `multiply(${left}, ${right})`
            case '/':
                return `divide(${left}, ${right})`
            case '%':
                return `modulo(${left}, ${right})`
            default:
                throw new Error(`Unknown ArithmeticOperation operator: ${op}`)
        }
    }

    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    private visitAsterisk(_: ASTNode): string {
        return '*'
    }

    private visitWindowExpr(node: ASTNode): string {
        if (!node) {
            return ''
        }
        const parts: string[] = []
        if (
            node.has('partition_by') &&
            Array.isArray(node.get('partition_by')) &&
            (node.get('partition_by') as ASTNode[]).length > 0
        ) {
            const partitions = (node.get('partition_by') as ASTNode[]).map((expr) => this.visit(expr)).join(', ')
            parts.push(`PARTITION BY ${partitions}`)
        }
        if (
            node.has('order_by') &&
            Array.isArray(node.get('order_by')) &&
            (node.get('order_by') as ASTNode[]).length > 0
        ) {
            const orders = (node.get('order_by') as ASTNode[]).map((expr) => this.visit(expr)).join(', ')
            parts.push(`ORDER BY ${orders}`)
        }
        if (node.has('frame_method')) {
            const frameMethod = node.get('frame_method') as string
            if (node.has('frame_start') && node.has('frame_end')) {
                parts.push(
                    `${frameMethod} BETWEEN ${this.visitWindowFrameExpr(
                        node.get('frame_start')
                    )} AND ${this.visitWindowFrameExpr(node.get('frame_end'))}`
                )
            } else if (node.has('frame_start')) {
                parts.push(`${frameMethod} ${this.visitWindowFrameExpr(node.get('frame_start'))}`)
            }
        }
        return parts.join(' ')
    }

    private visitWindowFunction(node: ASTNode): string {
        if (!node) {
            return ''
        }
        const name = node.get('name') as string
        const exprs = node.has('exprs')
            ? (node.get('exprs') as ASTNode[]).map((expr) => this.visit(expr)).join(', ')
            : ''
        const args = node.has('args')
            ? `(${(node.get('args') as ASTNode[]).map((arg) => this.visit(arg)).join(', ')})`
            : ''
        let over = ''
        if (node.has('over_expr')) {
            over = `(${this.visit(node.get('over_expr'))})`
        } else if (node.has('over_identifier')) {
            over = escapeIdentifier(node.get('over_identifier') as string)
        } else {
            over = '()'
        }
        return `${name}(${exprs})${args} OVER ${over}`
    }

    private visitWindowFrameExpr(node: ASTNode): string {
        if (!node) {
            return ''
        }
        const frameType = node.get('frame_type') as string
        const frameValue = node.has('frame_value') ? node.get('frame_value').toString() : 'UNBOUNDED'
        return `${frameValue} ${frameType}`
    }

    private visitSampleExpr(node: ASTNode): string {
        if (!node) {
            return ''
        }
        const sampleValue = this.visitRatioExpr(node.get('sample_value'))
        const offsetClause = node.has('offset_value') ? ` OFFSET ${this.visitRatioExpr(node.get('offset_value'))}` : ''
        return `SAMPLE ${sampleValue}${offsetClause}`
    }

    private visitHogQLXTag(node: ASTNode): string {
        if (!node) {
            return ''
        }
        const tagName = node.get('kind') as string
        const args = (node.get('attributes') || []) as ASTNode[]
        const argsString = args.length > 0 ? ` ${args.map((a) => this.visitHogQLXAttribute(a)).join(' ')}` : ''
        return `<${tagName}${argsString} />`
    }

    private visitHogQLXAttribute(node: ASTNode): string {
        if (!node) {
            return ''
        }
        const name = node.get('name') as string
        const value = this.visit(node.get('value'))
        if (typeof node.get('value') === 'string') {
            return `${escapeIdentifier(name)}=${value}`
        }
        return `${escapeIdentifier(name)}={${value}}`
    }

    private visitRatioExpr(node: ASTNode): string {
        if (!node) {
            return ''
        }
        if (node.has('right')) {
            return `${this.visit(node.get('left'))}/${this.visit(node.get('right'))}`
        }
        return this.visit(node.get('left'))
    }

    private escapeIdentifierOrIndex(name: string | number): string {
        if (typeof name === 'number' && /^\d+$/.test(name.toString())) {
            return name.toString()
        }
        return escapeIdentifier(name.toString())
    }

    private escapeValue(value: any): string {
        return printHogValue(value, this.marked)
    }
}
