import { executeHogQLBytecode, Operation as op } from '../../src/utils/hogql-bytecode'

describe('HogQL Bytecode', () => {
    test('execution results', () => {
        const fields = { properties: { foo: 'bar' } }
        expect(executeHogQLBytecode(['_h'], fields)).toBe(null)
        expect(executeHogQLBytecode(['_h', op.CONSTANT], fields)).toBe(null)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 2, op.CONSTANT, 1, op.PLUS], fields)).toBe(3)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 2, op.CONSTANT, 1, op.MINUS], fields)).toBe(-1)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 2, op.CONSTANT, 3, op.MULTIPLY], fields)).toBe(6)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 2, op.CONSTANT, 3, op.DIVIDE], fields)).toBe(1.5)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 2, op.CONSTANT, 3, op.MOD], fields)).toBe(1)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 2, op.CONSTANT, 1, op.AND, 2], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 0, op.CONSTANT, 1, op.OR, 2], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 0, op.CONSTANT, 1, op.AND, 2], fields)).toBe(false)
        expect(
            executeHogQLBytecode(
                ['_h', op.CONSTANT, 2, op.CONSTANT, 1, op.CONSTANT, 0, op.CONSTANT, 1, op.OR, 3],
                fields
            )
        ).toBe(true)
        expect(
            executeHogQLBytecode(
                ['_h', op.CONSTANT, 1, op.CONSTANT, 0, op.CONSTANT, 1, op.AND, 2, op.CONSTANT, 1, op.AND, 2],
                fields
            )
        ).toBe(false)
        expect(
            executeHogQLBytecode(
                ['_h', op.CONSTANT, 2, op.CONSTANT, 1, op.OR, 2, op.CONSTANT, 2, op.CONSTANT, 1, op.OR, 2, op.AND, 2],
                fields
            )
        ).toBe(true)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, true, op.NOT], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 2, op.CONSTANT, 1, op.EQ], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 2, op.CONSTANT, 1, op.NOT_EQ], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 2, op.CONSTANT, 1, op.LT], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 2, op.CONSTANT, 1, op.LT_EQ], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 2, op.CONSTANT, 1, op.GT], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 2, op.CONSTANT, 1, op.GT_EQ], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 'b', op.CONSTANT, 'a', op.LIKE], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, '%a%', op.CONSTANT, 'baa', op.LIKE], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, '%x%', op.CONSTANT, 'baa', op.LIKE], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, '%A%', op.CONSTANT, 'baa', op.ILIKE], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, '%C%', op.CONSTANT, 'baa', op.ILIKE], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 'b', op.CONSTANT, 'a', op.NOT_LIKE], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 'b', op.CONSTANT, 'a', op.NOT_ILIKE], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 'car', op.CONSTANT, 'a', op.IN], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 'car', op.CONSTANT, 'a', op.NOT_IN], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, '.*', op.CONSTANT, 'a', op.REGEX], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 'b', op.CONSTANT, 'a', op.REGEX], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, '.*', op.CONSTANT, 'a', op.NOT_REGEX], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 'b', op.CONSTANT, 'a', op.NOT_REGEX], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 'bla', op.CONSTANT, 'properties', op.FIELD, 2], fields)).toBe(
            null
        )
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 'foo', op.CONSTANT, 'properties', op.FIELD, 2], fields)).toBe(
            'bar'
        )
        expect(
            executeHogQLBytecode(['_h', op.CONSTANT, 'another', op.CONSTANT, 'arg', op.CALL, 'concat', 2], fields)
        ).toBe('arganother')
        expect(executeHogQLBytecode(['_h', op.CONSTANT, null, op.CONSTANT, 1, op.CALL, 'concat', 2], fields)).toBe('1')
        expect(executeHogQLBytecode(['_h', op.CONSTANT, false, op.CONSTANT, true, op.CALL, 'concat', 2], fields)).toBe(
            'truefalse'
        )
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 'e.*', op.CONSTANT, 'test', op.CALL, 'match', 2], fields)).toBe(
            true
        )
        expect(
            executeHogQLBytecode(['_h', op.CONSTANT, '^e.*', op.CONSTANT, 'test', op.CALL, 'match', 2], fields)
        ).toBe(false)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 'x.*', op.CONSTANT, 'test', op.CALL, 'match', 2], fields)).toBe(
            false
        )
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 1, op.CALL, 'toString', 1], fields)).toBe('1')
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 1.5, op.CALL, 'toString', 1], fields)).toBe('1.5')
        expect(executeHogQLBytecode(['_h', op.CONSTANT, true, op.CALL, 'toString', 1], fields)).toBe('true')
        expect(executeHogQLBytecode(['_h', op.CONSTANT, null, op.CALL, 'toString', 1], fields)).toBe('null')
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 'string', op.CALL, 'toString', 1], fields)).toBe('string')
        expect(executeHogQLBytecode(['_h', op.CONSTANT, '1', op.CALL, 'toInt', 1], fields)).toBe(1)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 'bla', op.CALL, 'toInt', 1], fields)).toBe(null)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, '1.2', op.CALL, 'toFloat', 1], fields)).toBe(1.2)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 'bla', op.CALL, 'toFloat', 1], fields)).toBe(null)
        expect(executeHogQLBytecode(['_h', op.CONSTANT, 'asd', op.CALL, 'toUUID', 1], fields)).toBe('asd')
    })

    test('error handling', () => {
        const fields = { properties: { foo: 'bar' } }

        expect(() => executeHogQLBytecode([], fields)).toThrowError("Invalid HogQL bytecode, must start with '_h'")
        expect(() => executeHogQLBytecode(['_h', op.CONSTANT, 2, op.CONSTANT, 1, 'InvalidOp'], fields)).toThrowError(
            'Unexpected node while running bytecode: InvalidOp'
        )
        expect(() =>
            executeHogQLBytecode(['_h', op.CONSTANT, 'another', op.CONSTANT, 'arg', op.CALL, 'invalidFunc', 2], fields)
        ).toThrowError('Unsupported function call: invalidFunc')
    })
})
