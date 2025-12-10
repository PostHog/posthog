import type * as ast from './ast'
import { CloningVisitor, TraversingVisitor, clearLocations, cloneExpr } from './visitor'

describe('HogQL Visitor', () => {
    // Helper to create a simple expression for testing
    const createConstant = (value: any): ast.Constant => ({
        value,
        start: { line: 1, column: 0, offset: 0 },
        end: { line: 1, column: 1, offset: 1 },
    })

    const createField = (chain: (string | number)[]): ast.Field => ({
        chain: chain as [string | number],
        start: { line: 1, column: 0, offset: 0 },
        end: { line: 1, column: 5, offset: 5 },
    })

    const createArithmeticOp = (
        left: ast.Expr,
        right: ast.Expr,
        op: ast.ArithmeticOperationOp
    ): ast.ArithmeticOperation => ({
        left,
        right,
        op,
        start: { line: 1, column: 0, offset: 0 },
        end: { line: 1, column: 10, offset: 10 },
    })

    const createCompareOp = (left: ast.Expr, right: ast.Expr, op: ast.CompareOperationOp): ast.CompareOperation => ({
        left,
        right,
        op,
        start: { line: 1, column: 0, offset: 0 },
        end: { line: 1, column: 10, offset: 10 },
    })

    describe('TraversingVisitor', () => {
        it('should traverse a constant node', () => {
            const visitor = new TraversingVisitor()
            const constant = createConstant(42)

            expect(() => visitor.visit(constant)).not.toThrow()
        })

        it('should traverse an arithmetic operation', () => {
            const visitor = new TraversingVisitor()
            const expr = createArithmeticOp(createConstant(1), createConstant(2), '+')

            expect(() => visitor.visit(expr)).not.toThrow()
        })

        it('should traverse nested expressions', () => {
            const visitor = new TraversingVisitor()
            // (1 + 2) * 3
            const expr = createArithmeticOp(
                createArithmeticOp(createConstant(1), createConstant(2), '+'),
                createConstant(3),
                '*'
            )

            expect(() => visitor.visit(expr)).not.toThrow()
        })

        it('should handle null nodes gracefully', () => {
            const visitor = new TraversingVisitor()
            expect(() => visitor.visit(null)).not.toThrow()
        })

        it('should traverse arrays', () => {
            const visitor = new TraversingVisitor()
            const array: ast.Array = {
                exprs: [createConstant(1), createConstant(2), createConstant(3)],
                start: { line: 1, column: 0, offset: 0 },
                end: { line: 1, column: 10, offset: 10 },
            }

            expect(() => visitor.visit(array)).not.toThrow()
        })

        it('should traverse tuples', () => {
            const visitor = new TraversingVisitor()
            const tuple: ast.Tuple = {
                exprs: [createConstant('a'), createConstant('b')],
                start: { line: 1, column: 0, offset: 0 },
                end: { line: 1, column: 10, offset: 10 },
            }

            expect(() => visitor.visit(tuple)).not.toThrow()
        })

        it('should traverse function calls', () => {
            const visitor = new TraversingVisitor()
            const call: ast.Call = {
                name: 'toString',
                args: [createField(['user_id'])],
                start: { line: 1, column: 0, offset: 0 },
                end: { line: 1, column: 15, offset: 15 },
            }

            expect(() => visitor.visit(call)).not.toThrow()
        })

        it('should traverse SELECT queries', () => {
            const visitor = new TraversingVisitor()
            const selectQuery: ast.SelectQuery = {
                select: [createField(['user_id']), createField(['timestamp'])],
                start: { line: 1, column: 0, offset: 0 },
                end: { line: 2, column: 0, offset: 50 },
            }

            expect(() => visitor.visit(selectQuery)).not.toThrow()
        })

        it('should count visited nodes', () => {
            class CountingVisitor extends TraversingVisitor {
                count = 0

                visit_constant(node: ast.Constant): void {
                    this.count++
                    super.visit_constant(node)
                }

                visit_arithmetic_operation(node: ast.ArithmeticOperation): void {
                    this.count++
                    super.visit_arithmetic_operation(node)
                }
            }

            const visitor = new CountingVisitor()
            // 1 + 2
            const expr = createArithmeticOp(createConstant(1), createConstant(2), '+')

            visitor.visit(expr)
            expect(visitor.count).toBe(3) // 1 ArithmeticOperation + 2 Constants
        })
    })

    describe('CloningVisitor', () => {
        it('should clone a constant node', () => {
            const constant = createConstant(42)
            const cloned = cloneExpr(constant)

            expect(cloned).not.toBe(constant)
            expect(cloned.value).toBe(42)
        })

        it('should clone an arithmetic operation', () => {
            const expr = createArithmeticOp(createConstant(1), createConstant(2), '+')
            const cloned = cloneExpr(expr) as ast.ArithmeticOperation

            expect(cloned).not.toBe(expr)
            expect(cloned.op).toBe('+')
            expect((cloned.left as ast.Constant).value).toBe(1)
            expect((cloned.right as ast.Constant).value).toBe(2)
        })

        it('should clone nested expressions', () => {
            // (1 + 2) * 3
            const expr = createArithmeticOp(
                createArithmeticOp(createConstant(1), createConstant(2), '+'),
                createConstant(3),
                '*'
            )
            const cloned = cloneExpr(expr) as ast.ArithmeticOperation

            expect(cloned).not.toBe(expr)
            expect(cloned.op).toBe('*')

            const left = cloned.left as ast.ArithmeticOperation
            expect(left.op).toBe('+')
            expect((left.left as ast.Constant).value).toBe(1)
            expect((left.right as ast.Constant).value).toBe(2)
            expect((cloned.right as ast.Constant).value).toBe(3)
        })

        it('should clear types by default', () => {
            const constant: ast.Constant = {
                value: 42,
                type: { data_type: 'int' } as ast.IntegerType,
                start: { line: 1, column: 0, offset: 0 },
                end: { line: 1, column: 2, offset: 2 },
            }

            const cloned = cloneExpr(constant)
            expect(cloned.type).toBeUndefined()
        })

        it('should preserve types when clearTypes is false', () => {
            const constant: ast.Constant = {
                value: 42,
                type: { data_type: 'int' } as ast.IntegerType,
                start: { line: 1, column: 0, offset: 0 },
                end: { line: 1, column: 2, offset: 2 },
            }

            const cloned = cloneExpr(constant, { clearTypes: false })
            expect(cloned.type).toBeTruthy()
            expect((cloned.type as ast.IntegerType).data_type).toBe('int')
        })

        it('should preserve locations by default', () => {
            const constant = createConstant(42)
            const cloned = cloneExpr(constant)

            expect(cloned.start).toBeTruthy()
            expect(cloned.start?.line).toBe(1)
            expect(cloned.end).toBeTruthy()
        })

        it('should clear locations when clearLocations is true', () => {
            const constant = createConstant(42)
            const cloned = clearLocations(constant)

            expect(cloned.start).toBeUndefined()
            expect(cloned.end).toBeUndefined()
        })

        it('should clone arrays', () => {
            const array: ast.Array = {
                exprs: [createConstant(1), createConstant(2), createConstant(3)],
                start: { line: 1, column: 0, offset: 0 },
                end: { line: 1, column: 10, offset: 10 },
            }

            const cloned = cloneExpr(array) as ast.Array
            expect(cloned).not.toBe(array)
            expect(cloned.exprs).toHaveLength(3)
            expect(cloned.exprs[0]).not.toBe(array.exprs[0])
            expect((cloned.exprs[0] as ast.Constant).value).toBe(1)
        })

        it('should clone tuples', () => {
            const tuple: ast.Tuple = {
                exprs: [createConstant('a'), createConstant('b')],
                start: { line: 1, column: 0, offset: 0 },
                end: { line: 1, column: 10, offset: 10 },
            }

            const cloned = cloneExpr(tuple) as ast.Tuple
            expect(cloned).not.toBe(tuple)
            expect(cloned.exprs).toHaveLength(2)
            expect((cloned.exprs[0] as ast.Constant).value).toBe('a')
        })

        it('should clone function calls', () => {
            const call: ast.Call = {
                name: 'toString',
                args: [createField(['user_id'])],
                distinct: false,
                start: { line: 1, column: 0, offset: 0 },
                end: { line: 1, column: 15, offset: 15 },
            }

            const cloned = cloneExpr(call) as ast.Call
            expect(cloned).not.toBe(call)
            expect(cloned.name).toBe('toString')
            expect(cloned.args).toHaveLength(1)
            expect(cloned.args[0]).not.toBe(call.args[0])
        })

        it('should clone fields', () => {
            const field = createField(['events', 'timestamp'])
            const cloned = cloneExpr(field) as ast.Field

            expect(cloned).not.toBe(field)
            expect(cloned.chain).toEqual(['events', 'timestamp'])
            expect(cloned.chain).not.toBe(field.chain) // Array should be copied
        })

        it('should clone SELECT queries', () => {
            const selectQuery: ast.SelectQuery = {
                select: [createField(['user_id']), createField(['timestamp'])],
                where: createCompareOp(createField(['count']), createConstant(10), '>'),
                start: { line: 1, column: 0, offset: 0 },
                end: { line: 2, column: 0, offset: 50 },
            }

            const cloned = cloneExpr(selectQuery) as ast.SelectQuery
            expect(cloned).not.toBe(selectQuery)
            expect(cloned.select).toHaveLength(2)
            expect(cloned.select[0]).not.toBe(selectQuery.select[0])
            expect(cloned.where).toBeTruthy()
            expect(cloned.where).not.toBe(selectQuery.where)
        })

        it('should clone And expressions', () => {
            const andExpr: ast.And = {
                exprs: [
                    createCompareOp(createField(['x']), createConstant(1), '>'),
                    createCompareOp(createField(['y']), createConstant(2), '<'),
                ],
                start: { line: 1, column: 0, offset: 0 },
                end: { line: 1, column: 20, offset: 20 },
            }

            const cloned = cloneExpr(andExpr) as ast.And
            expect(cloned).not.toBe(andExpr)
            expect(cloned.exprs).toHaveLength(2)
            expect(cloned.exprs[0]).not.toBe(andExpr.exprs[0])
        })

        it('should clone Or expressions', () => {
            const orExpr: ast.Or = {
                exprs: [createConstant(true), createConstant(false)],
                start: { line: 1, column: 0, offset: 0 },
                end: { line: 1, column: 10, offset: 10 },
            }

            const cloned = cloneExpr(orExpr) as ast.Or
            expect(cloned).not.toBe(orExpr)
            expect(cloned.exprs).toHaveLength(2)
        })

        it('should clone Compare operations', () => {
            const compareOp: ast.CompareOperation = {
                left: createField(['age']),
                right: createConstant(18),
                op: '>=',
                start: { line: 1, column: 0, offset: 0 },
                end: { line: 1, column: 10, offset: 10 },
            }

            const cloned = cloneExpr(compareOp) as ast.CompareOperation
            expect(cloned).not.toBe(compareOp)
            expect(cloned.op).toBe('>=')
            expect(cloned.left).not.toBe(compareOp.left)
            expect(cloned.right).not.toBe(compareOp.right)
        })

        it('should clone Not expressions', () => {
            const notExpr: ast.Not = {
                expr: createConstant(true),
                start: { line: 1, column: 0, offset: 0 },
                end: { line: 1, column: 5, offset: 5 },
            }

            const cloned = cloneExpr(notExpr) as ast.Not
            expect(cloned).not.toBe(notExpr)
            expect(cloned.expr).not.toBe(notExpr.expr)
        })

        it('should clone Alias expressions', () => {
            const alias: ast.Alias = {
                alias: 'user_count',
                expr: createField(['count']),
                start: { line: 1, column: 0, offset: 0 },
                end: { line: 1, column: 15, offset: 15 },
            }

            const cloned = cloneExpr(alias) as ast.Alias
            expect(cloned).not.toBe(alias)
            expect(cloned.alias).toBe('user_count')
            expect(cloned.expr).not.toBe(alias.expr)
        })

        it('should clone Lambda expressions', () => {
            const lambda: ast.Lambda = {
                args: ['x', 'y'],
                expr: createArithmeticOp(createField(['x']), createField(['y']), '+'),
                start: { line: 1, column: 0, offset: 0 },
                end: { line: 1, column: 20, offset: 20 },
            }

            const cloned = cloneExpr(lambda) as ast.Lambda
            expect(cloned).not.toBe(lambda)
            expect(cloned.args).toEqual(['x', 'y'])
            expect(cloned.args).not.toBe(lambda.args) // Array should be copied
            expect(cloned.expr).not.toBe(lambda.expr)
        })
    })

    describe('Custom Visitors', () => {
        it('should allow custom visitor implementations', () => {
            class ReplaceConstantVisitor extends CloningVisitor {
                constructor(
                    private oldValue: any,
                    private newValue: any
                ) {
                    super(true, false, false)
                }

                visit_constant(node: ast.Constant): ast.Constant {
                    if (node.value === this.oldValue) {
                        return {
                            ...super.visit_constant(node),
                            value: this.newValue,
                        }
                    }
                    return super.visit_constant(node)
                }
            }

            const expr = createArithmeticOp(createConstant(1), createConstant(2), '+')
            const visitor = new ReplaceConstantVisitor(2, 5)
            const result = visitor.visit(expr) as ast.ArithmeticOperation

            expect((result.left as ast.Constant).value).toBe(1)
            expect((result.right as ast.Constant).value).toBe(5)
        })

        it('should allow collecting information during traversal', () => {
            class FieldCollector extends TraversingVisitor {
                fields: string[][] = []

                visit_field(node: ast.Field): void {
                    this.fields.push([...node.chain] as string[])
                    super.visit_field(node)
                }
            }

            const selectQuery: ast.SelectQuery = {
                select: [createField(['user_id']), createField(['timestamp'])],
                where: createCompareOp(createField(['count']), createConstant(10), '>'),
                start: { line: 1, column: 0, offset: 0 },
                end: { line: 2, column: 0, offset: 50 },
            }

            const collector = new FieldCollector()
            collector.visit(selectQuery)

            expect(collector.fields).toHaveLength(3)
            expect(collector.fields).toContainEqual(['user_id'])
            expect(collector.fields).toContainEqual(['timestamp'])
            expect(collector.fields).toContainEqual(['count'])
        })

        it('should allow transforming expressions', () => {
            class DoubleConstantsVisitor extends CloningVisitor {
                visit_constant(node: ast.Constant): ast.Constant {
                    const cloned = super.visit_constant(node)
                    if (typeof cloned.value === 'number') {
                        return { ...cloned, value: cloned.value * 2 }
                    }
                    return cloned
                }
            }

            const expr = createArithmeticOp(createConstant(5), createConstant(10), '+')
            const visitor = new DoubleConstantsVisitor(true, false, false)
            const result = visitor.visit(expr) as ast.ArithmeticOperation

            expect((result.left as ast.Constant).value).toBe(10)
            expect((result.right as ast.Constant).value).toBe(20)
        })
    })

    describe('Edge Cases', () => {
        it('should handle empty arrays', () => {
            const array: ast.Array = {
                exprs: [],
                start: { line: 1, column: 0, offset: 0 },
                end: { line: 1, column: 2, offset: 2 },
            }

            const cloned = cloneExpr(array) as ast.Array
            expect(cloned.exprs).toHaveLength(0)
        })

        it('should handle null/undefined child nodes', () => {
            const selectQuery: ast.SelectQuery = {
                select: [createField(['user_id'])],
                where: undefined,
                start: { line: 1, column: 0, offset: 0 },
                end: { line: 1, column: 20, offset: 20 },
            }

            const cloned = cloneExpr(selectQuery) as ast.SelectQuery
            expect(cloned.where).toBeUndefined()
        })

        it('should handle deeply nested expressions', () => {
            // Create a deeply nested expression: ((((1 + 2) + 3) + 4) + 5)
            let expr: ast.Expr = createConstant(1)
            for (let i = 2; i <= 5; i++) {
                expr = createArithmeticOp(expr, createConstant(i), '+')
            }

            const cloned = cloneExpr(expr) as ast.ArithmeticOperation
            expect(cloned).not.toBe(expr)

            // Verify the structure is preserved
            let current = cloned
            for (let i = 5; i >= 2; i--) {
                expect(current.op).toBe('+')
                expect((current.right as ast.Constant).value).toBe(i)
                if (i > 2) {
                    current = current.left as ast.ArithmeticOperation
                }
            }
        })
    })
})
