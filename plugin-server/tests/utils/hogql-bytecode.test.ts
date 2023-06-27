import { executeHogQLBytecode, Operation as op } from '../../src/utils/hogql-bytecode'

describe('HogQL Bytecode', () => {
    test('execution results', () => {
        const fields = { properties: { foo: 'bar' } }
        expect(executeHogQLBytecode(['_h'], fields)).toBe(null)
        expect(executeHogQLBytecode(['_h', op.INTEGER], fields)).toBe(null)
        expect(executeHogQLBytecode(['_h', op.INTEGER, 2, op.INTEGER, 1, op.PLUS], fields)).toBe(3)
        expect(executeHogQLBytecode(['_h', op.INTEGER, 2, op.INTEGER, 1, op.MINUS], fields)).toBe(-1)
        expect(executeHogQLBytecode(['_h', op.INTEGER, 2, op.INTEGER, 3, op.MULTIPLY], fields)).toBe(6)
        expect(executeHogQLBytecode(['_h', op.INTEGER, 2, op.INTEGER, 3, op.DIVIDE], fields)).toBe(1.5)
        expect(executeHogQLBytecode(['_h', op.INTEGER, 2, op.INTEGER, 3, op.MOD], fields)).toBe(1)
        expect(executeHogQLBytecode(['_h', op.INTEGER, 2, op.INTEGER, 1, op.AND, 2], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.INTEGER, 0, op.INTEGER, 1, op.OR, 2], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.INTEGER, 0, op.INTEGER, 1, op.AND, 2], fields)).toBe(false)
        expect(
            executeHogQLBytecode(['_h', op.INTEGER, 2, op.INTEGER, 1, op.INTEGER, 0, op.INTEGER, 1, op.OR, 3], fields)
        ).toBe(true)
        expect(
            executeHogQLBytecode(
                ['_h', op.INTEGER, 1, op.INTEGER, 0, op.INTEGER, 1, op.AND, 2, op.INTEGER, 1, op.AND, 2],
                fields
            )
        ).toBe(false)
        expect(
            executeHogQLBytecode(
                ['_h', op.INTEGER, 2, op.INTEGER, 1, op.OR, 2, op.INTEGER, 2, op.INTEGER, 1, op.OR, 2, op.AND, 2],
                fields
            )
        ).toBe(true)
        expect(executeHogQLBytecode(['_h', op.TRUE, op.NOT], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', op.INTEGER, 2, op.INTEGER, 1, op.EQ], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', op.INTEGER, 2, op.INTEGER, 1, op.NOT_EQ], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.INTEGER, 2, op.INTEGER, 1, op.LT], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.INTEGER, 2, op.INTEGER, 1, op.LT_EQ], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.INTEGER, 2, op.INTEGER, 1, op.GT], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', op.INTEGER, 2, op.INTEGER, 1, op.GT_EQ], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', op.STRING, 'b', op.STRING, 'a', op.LIKE], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', op.STRING, '%a%', op.STRING, 'baa', op.LIKE], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.STRING, '%x%', op.STRING, 'baa', op.LIKE], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', op.STRING, '%A%', op.STRING, 'baa', op.ILIKE], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.STRING, '%C%', op.STRING, 'baa', op.ILIKE], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', op.STRING, 'b', op.STRING, 'a', op.NOT_LIKE], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.STRING, 'b', op.STRING, 'a', op.NOT_ILIKE], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.STRING, 'car', op.STRING, 'a', op.IN], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.STRING, 'car', op.STRING, 'a', op.NOT_IN], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', op.STRING, '.*', op.STRING, 'a', op.REGEX], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.STRING, 'b', op.STRING, 'a', op.REGEX], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', op.STRING, '.*', op.STRING, 'a', op.NOT_REGEX], fields)).toBe(false)
        expect(executeHogQLBytecode(['_h', op.STRING, 'b', op.STRING, 'a', op.NOT_REGEX], fields)).toBe(true)
        expect(executeHogQLBytecode(['_h', op.STRING, 'bla', op.STRING, 'properties', op.FIELD, 2], fields)).toBe(null)
        expect(executeHogQLBytecode(['_h', op.STRING, 'foo', op.STRING, 'properties', op.FIELD, 2], fields)).toBe('bar')
        expect(executeHogQLBytecode(['_h', op.STRING, 'another', op.STRING, 'arg', op.CALL, 'concat', 2], fields)).toBe(
            'arganother'
        )
        expect(executeHogQLBytecode(['_h', op.NULL, op.INTEGER, 1, op.CALL, 'concat', 2], fields)).toBe('1')
        expect(executeHogQLBytecode(['_h', op.FALSE, op.TRUE, op.CALL, 'concat', 2], fields)).toBe('truefalse')
        expect(executeHogQLBytecode(['_h', op.STRING, 'e.*', op.STRING, 'test', op.CALL, 'match', 2], fields)).toBe(
            true
        )
        expect(executeHogQLBytecode(['_h', op.STRING, '^e.*', op.STRING, 'test', op.CALL, 'match', 2], fields)).toBe(
            false
        )
        expect(executeHogQLBytecode(['_h', op.STRING, 'x.*', op.STRING, 'test', op.CALL, 'match', 2], fields)).toBe(
            false
        )
        expect(executeHogQLBytecode(['_h', op.INTEGER, 1, op.CALL, 'toString', 1], fields)).toBe('1')
        expect(executeHogQLBytecode(['_h', op.FLOAT, 1.5, op.CALL, 'toString', 1], fields)).toBe('1.5')
        expect(executeHogQLBytecode(['_h', op.TRUE, op.CALL, 'toString', 1], fields)).toBe('true')
        expect(executeHogQLBytecode(['_h', op.NULL, op.CALL, 'toString', 1], fields)).toBe('null')
        expect(executeHogQLBytecode(['_h', op.STRING, 'string', op.CALL, 'toString', 1], fields)).toBe('string')
        expect(executeHogQLBytecode(['_h', op.STRING, '1', op.CALL, 'toInt', 1], fields)).toBe(1)
        expect(executeHogQLBytecode(['_h', op.STRING, 'bla', op.CALL, 'toInt', 1], fields)).toBe(null)
        expect(executeHogQLBytecode(['_h', op.STRING, '1.2', op.CALL, 'toFloat', 1], fields)).toBe(1.2)
        expect(executeHogQLBytecode(['_h', op.STRING, 'bla', op.CALL, 'toFloat', 1], fields)).toBe(null)
        expect(executeHogQLBytecode(['_h', op.STRING, 'asd', op.CALL, 'toUUID', 1], fields)).toBe('asd')
    })

    test('error handling', () => {
        const fields = { properties: { foo: 'bar' } }

        expect(() => executeHogQLBytecode([], fields)).toThrowError("Invalid HogQL bytecode, must start with '_h'")
        expect(() => executeHogQLBytecode(['_h', op.INTEGER, 2, op.INTEGER, 1, 'InvalidOp'], fields)).toThrowError(
            'Unexpected node while running bytecode: InvalidOp'
        )
        expect(() =>
            executeHogQLBytecode(['_h', op.STRING, 'another', op.STRING, 'arg', op.CALL, 'invalidFunc', 2], fields)
        ).toThrowError('Unsupported function call: invalidFunc')
    })
})
