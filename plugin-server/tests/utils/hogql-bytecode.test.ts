import { BinaryOperationOp, CompareOperationOp, executeHogQLBytecode, Operation } from '../../src/utils/hogql-bytecode'

describe('HogQL Bytecode', () => {
    test('execution results', () => {
        const fields = { properties: { foo: 'bar' } }
        expect(executeHogQLBytecode(['_h'], fields)).toBe(null)
        expect(executeHogQLBytecode(['_h', ''], fields)).toBe(null)
        expect(executeHogQLBytecode(['_h', '', 2, '', 1, BinaryOperationOp.Add], fields)).toBe(3)
        expect(executeHogQLBytecode(['_h', '', 2, '', 1, BinaryOperationOp.Sub], fields)).toBe(-1)
        expect(executeHogQLBytecode(['_h', '', 2, '', 3, BinaryOperationOp.Mult], fields)).toBe(6)
        expect(executeHogQLBytecode(['_h', '', 2, '', 3, BinaryOperationOp.Div], fields)).toBe(1.5)
        expect(executeHogQLBytecode(['_h', '', 2, '', 3, BinaryOperationOp.Mod], fields)).toBe(1)
        expect(executeHogQLBytecode(['_h', '', 2, '', 1, Operation.AND, 2], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', '', 0, '', 1, Operation.OR, 2], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', '', 0, '', 1, Operation.AND, 2], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', '', 2, '', 1, '', 0, '', 1, Operation.OR, 3], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', '', 1, '', 0, '', 1, 'and', 2, '', 1, 'and', 2], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', '', 2, '', 1, 'or', 2, '', 2, '', 1, 'or', 2, 'and', 2], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', '', true, Operation.NOT], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', '', 2, '', 1, CompareOperationOp.Eq], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', '', 2, '', 1, CompareOperationOp.NotEq], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', '', 2, '', 1, CompareOperationOp.Lt], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', '', 2, '', 1, CompareOperationOp.LtE], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', '', 2, '', 1, CompareOperationOp.Gt], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', '', 2, '', 1, CompareOperationOp.GtE], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', '', 'b', '', 'a', CompareOperationOp.Like], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', '', '%a%', '', 'baa', CompareOperationOp.Like], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', '', '%x%', '', 'baa', CompareOperationOp.Like], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', '', '%A%', '', 'baa', CompareOperationOp.ILike], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', '', '%C%', '', 'baa', CompareOperationOp.ILike], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', '', 'b', '', 'a', CompareOperationOp.NotLike], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', '', 'b', '', 'a', CompareOperationOp.NotILike], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', '', 'car', '', 'a', CompareOperationOp.In], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', '', 'car', '', 'a', CompareOperationOp.NotIn], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', '', '.*', '', 'a', CompareOperationOp.Regex], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', '', 'b', '', 'a', CompareOperationOp.Regex], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', '', '.*', '', 'a', CompareOperationOp.NotRegex], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', '', 'b', '', 'a', CompareOperationOp.NotRegex], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', '', 'bla', '', 'properties', Operation.FIELD, 2], fields)).toBe(null)
        expect(executeHogQLBytecode(['_h', '', 'foo', '', 'properties', Operation.FIELD, 2], fields)).toBe('bar')
        expect(executeHogQLBytecode(['_h', '', 'another', '', 'arg', Operation.CALL, 'concat', 2], fields)).toBe(
            'arganother'
        )
        expect(executeHogQLBytecode(['_h', '', null, '', 1, Operation.CALL, 'concat', 2], fields)).toBe('1')
        expect(executeHogQLBytecode(['_h', '', false, '', true, Operation.CALL, 'concat', 2], fields)).toBe('truefalse')
        expect(executeHogQLBytecode(['_h', '', 'e.*', '', 'test', Operation.CALL, 'match', 2], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', '', '^e.*', '', 'test', Operation.CALL, 'match', 2], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', '', 'x.*', '', 'test', Operation.CALL, 'match', 2], fields)).toBe(false)
    })

    test('error handling', () => {
        const fields = { properties: { foo: 'bar' } }

        expect(() => executeHogQLBytecode([], fields)).toThrowError("Invalid HogQL bytecode, must start with '_h'")
        expect(() => executeHogQLBytecode(['_h', '', 2, '', 1, 'InvalidOp'], fields)).toThrowError(
            'Unexpected node while running bytecode: InvalidOp'
        )
        expect(() =>
            executeHogQLBytecode(['_h', '', 'another', '', 'arg', '()', 'invalidFunc', 2], fields)
        ).toThrowError('Unsupported function call: invalidFunc')
    })
})
