import { BinaryOperationOp, CompareOperationOp, executeHogQLBytecode, Operation } from '../../src/utils/hogql-bytecode'

describe('HogQL Bytecode', () => {
    test('execution results', () => {
        const fields = { properties: { foo: 'bar' } }
        expect(executeHogQLBytecode([], fields)).toBe(null)
        expect(executeHogQLBytecode([''], fields)).toBe(null)
        expect(executeHogQLBytecode(['', 2, '', 1, BinaryOperationOp.Add], fields)).toBe(3)
        expect(executeHogQLBytecode(['', 2, '', 1, BinaryOperationOp.Sub], fields)).toBe(-1)
        expect(executeHogQLBytecode(['', 2, '', 3, BinaryOperationOp.Mult], fields)).toBe(6)
        expect(executeHogQLBytecode(['', 2, '', 3, BinaryOperationOp.Div], fields)).toBe(1.5)
        expect(executeHogQLBytecode(['', 2, '', 3, BinaryOperationOp.Mod], fields)).toBe(1)
        expect(executeHogQLBytecode(['', 2, '', 1, Operation.AND, 2], fields)).toBe(true)
        expect(executeHogQLBytecode(['', 0, '', 1, Operation.OR, 2], fields)).toBe(true)
        expect(executeHogQLBytecode(['', 0, '', 1, Operation.AND, 2], fields)).toBe(false)
        expect(executeHogQLBytecode(['', 2, '', 1, '', 0, '', 1, Operation.OR, 3], fields)).toBe(true)
        expect(executeHogQLBytecode(['', 1, '', 0, '', 1, 'and', 2, '', 1, 'and', 2], fields)).toBe(false)
        expect(executeHogQLBytecode(['', 2, '', 1, 'or', 2, '', 2, '', 1, 'or', 2, 'and', 2], fields)).toBe(true)
        expect(executeHogQLBytecode(['', true, Operation.NOT], fields)).toBe(false)
        expect(executeHogQLBytecode(['', 2, '', 1, CompareOperationOp.Eq], fields)).toBe(false)
        expect(executeHogQLBytecode(['', 2, '', 1, CompareOperationOp.NotEq], fields)).toBe(true)
        expect(executeHogQLBytecode(['', 2, '', 1, CompareOperationOp.Lt], fields)).toBe(true)
        expect(executeHogQLBytecode(['', 2, '', 1, CompareOperationOp.LtE], fields)).toBe(true)
        expect(executeHogQLBytecode(['', 2, '', 1, CompareOperationOp.Gt], fields)).toBe(false)
        expect(executeHogQLBytecode(['', 2, '', 1, CompareOperationOp.GtE], fields)).toBe(false)
        expect(executeHogQLBytecode(['', 'b', '', 'a', CompareOperationOp.Like], fields)).toBe(false)
        expect(executeHogQLBytecode(['', '%a%', '', 'baa', CompareOperationOp.Like], fields)).toBe(true)
        expect(executeHogQLBytecode(['', '%x%', '', 'baa', CompareOperationOp.Like], fields)).toBe(false)
        expect(executeHogQLBytecode(['', '%A%', '', 'baa', CompareOperationOp.ILike], fields)).toBe(true)
        expect(executeHogQLBytecode(['', '%C%', '', 'baa', CompareOperationOp.ILike], fields)).toBe(false)
        expect(executeHogQLBytecode(['', 'b', '', 'a', CompareOperationOp.NotLike], fields)).toBe(true)
        expect(executeHogQLBytecode(['', 'b', '', 'a', CompareOperationOp.NotILike], fields)).toBe(true)
        expect(executeHogQLBytecode(['', 'car', '', 'a', CompareOperationOp.In], fields)).toBe(true)
        expect(executeHogQLBytecode(['', 'car', '', 'a', CompareOperationOp.NotIn], fields)).toBe(false)
        expect(executeHogQLBytecode(['', 'bla', '', 'properties', Operation.FIELD, 2], fields)).toBe(null)
        expect(executeHogQLBytecode(['', 'foo', '', 'properties', Operation.FIELD, 2], fields)).toBe('bar')
        expect(executeHogQLBytecode(['', 'another', '', 'arg', Operation.CALL, 'concat', 2], fields)).toBe('arganother')
        expect(executeHogQLBytecode(['', null, '', 1, Operation.CALL, 'concat', 2], fields)).toBe('1')
        expect(executeHogQLBytecode(['', false, '', true, Operation.CALL, 'concat', 2], fields)).toBe('truefalse')
    })

    test('error handling', () => {
        const fields = { properties: { foo: 'bar' } }

        expect(() => executeHogQLBytecode(['', 2, '', 1, 'InvalidOp'], fields)).toThrowError(
            'Unexpected node while running bytecode: InvalidOp'
        )
        expect(() => executeHogQLBytecode(['', 'another', '', 'arg', '()', 'invalidFunc', 2], fields)).toThrowError(
            'Unsupported function call: invalidFunc'
        )
    })
})
