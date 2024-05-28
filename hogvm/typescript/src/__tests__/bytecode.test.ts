import { exec, execAsync, execSync, Operation as op } from '../bytecode'

export function delay(ms: number): Promise<void> {
    return new Promise((resolve) => {
        setTimeout(resolve, ms)
    })
}

describe('HogQL Bytecode', () => {
    test('execution results', async () => {
        const fields = { properties: { foo: 'bar', nullValue: null } }
        expect(execSync(['_h'], fields)).toBe(null)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 1, op.PLUS], fields)).toBe(3)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 1, op.MINUS], fields)).toBe(-1)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 3, op.MULTIPLY], fields)).toBe(6)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 3, op.DIVIDE], fields)).toBe(1.5)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 3, op.MOD], fields)).toBe(1)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 1, op.AND, 2], fields)).toBe(true)
        expect(execSync(['_h', op.INTEGER, 0, op.INTEGER, 1, op.OR, 2], fields)).toBe(true)
        expect(execSync(['_h', op.INTEGER, 0, op.INTEGER, 1, op.AND, 2], fields)).toBe(false)
        expect(execSync(['_h', op.INTEGER, 1, op.INTEGER, 0, op.INTEGER, 1, op.OR, 3], fields)).toBe(true)
        expect(execSync(['_h', op.INTEGER, 0, op.INTEGER, 1, op.AND, 2, op.INTEGER, 1, op.AND, 2], fields)).toBe(false)
        expect(
            execSync(
                ['_h', op.INTEGER, 2, op.INTEGER, 1, op.OR, 2, op.INTEGER, 2, op.INTEGER, 1, op.OR, 2, op.AND, 2],
                fields
            )
        ).toBe(true)
        expect(execSync(['_h', op.TRUE, op.NOT], fields)).toBe(false)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 1, op.EQ], fields)).toBe(false)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 1, op.NOT_EQ], fields)).toBe(true)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 1, op.LT], fields)).toBe(true)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 1, op.LT_EQ], fields)).toBe(true)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 1, op.GT], fields)).toBe(false)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 1, op.GT_EQ], fields)).toBe(false)
        expect(execSync(['_h', op.STRING, 'b', op.STRING, 'a', op.LIKE], fields)).toBe(false)
        expect(execSync(['_h', op.STRING, '%a%', op.STRING, 'baa', op.LIKE], fields)).toBe(true)
        expect(execSync(['_h', op.STRING, '%x%', op.STRING, 'baa', op.LIKE], fields)).toBe(false)
        expect(execSync(['_h', op.STRING, '%A%', op.STRING, 'baa', op.ILIKE], fields)).toBe(true)
        expect(execSync(['_h', op.STRING, '%C%', op.STRING, 'baa', op.ILIKE], fields)).toBe(false)
        expect(execSync(['_h', op.STRING, 'b', op.STRING, 'a', op.NOT_LIKE], fields)).toBe(true)
        expect(execSync(['_h', op.STRING, 'b', op.STRING, 'a', op.NOT_ILIKE], fields)).toBe(true)
        expect(execSync(['_h', op.STRING, 'car', op.STRING, 'a', op.IN], fields)).toBe(true)
        expect(execSync(['_h', op.STRING, 'car', op.STRING, 'a', op.NOT_IN], fields)).toBe(false)
        expect(execSync(['_h', op.STRING, '.*', op.STRING, 'a', op.REGEX], fields)).toBe(true)
        expect(execSync(['_h', op.STRING, 'b', op.STRING, 'a', op.REGEX], fields)).toBe(false)
        expect(execSync(['_h', op.STRING, '.*', op.STRING, 'a', op.NOT_REGEX], fields)).toBe(false)
        expect(execSync(['_h', op.STRING, 'b', op.STRING, 'a', op.NOT_REGEX], fields)).toBe(true)
        expect(execSync(['_h', op.STRING, '.*', op.STRING, 'kala', op.IREGEX], fields)).toBe(true)
        expect(execSync(['_h', op.STRING, 'b', op.STRING, 'kala', op.IREGEX], fields)).toBe(false)
        expect(execSync(['_h', op.STRING, 'AL', op.STRING, 'kala', op.IREGEX], fields)).toBe(true)
        expect(execSync(['_h', op.STRING, '.*', op.STRING, 'kala', op.NOT_IREGEX], fields)).toBe(false)
        expect(execSync(['_h', op.STRING, 'b', op.STRING, 'kala', op.NOT_IREGEX], fields)).toBe(true)
        expect(execSync(['_h', op.STRING, 'AL', op.STRING, 'kala', op.NOT_IREGEX], fields)).toBe(false)
        expect(execSync(['_h', op.STRING, 'bla', op.STRING, 'properties', op.FIELD, 2], fields)).toBe(null)
        expect(execSync(['_h', op.STRING, 'foo', op.STRING, 'properties', op.FIELD, 2], fields)).toBe('bar')
        expect(
            execSync(
                ['_h', op.FALSE, op.STRING, 'foo', op.STRING, 'properties', op.FIELD, 2, op.CALL, 'ifNull', 2],
                fields
            )
        ).toBe('bar')
        expect(
            execSync(
                ['_h', op.FALSE, op.STRING, 'nullValue', op.STRING, 'properties', op.FIELD, 2, op.CALL, 'ifNull', 2],
                fields
            )
        ).toBe(false)
        expect(execSync(['_h', op.STRING, 'another', op.STRING, 'arg', op.CALL, 'concat', 2], fields)).toBe(
            'arganother'
        )
        expect(execSync(['_h', op.NULL, op.INTEGER, 1, op.CALL, 'concat', 2], fields)).toBe('1')
        expect(execSync(['_h', op.FALSE, op.TRUE, op.CALL, 'concat', 2], fields)).toBe('truefalse')
        expect(execSync(['_h', op.STRING, 'e.*', op.STRING, 'test', op.CALL, 'match', 2], fields)).toBe(true)
        expect(execSync(['_h', op.STRING, '^e.*', op.STRING, 'test', op.CALL, 'match', 2], fields)).toBe(false)
        expect(execSync(['_h', op.STRING, 'x.*', op.STRING, 'test', op.CALL, 'match', 2], fields)).toBe(false)
        expect(execSync(['_h', op.INTEGER, 1, op.CALL, 'toString', 1], fields)).toBe('1')
        expect(execSync(['_h', op.FLOAT, 1.5, op.CALL, 'toString', 1], fields)).toBe('1.5')
        expect(execSync(['_h', op.TRUE, op.CALL, 'toString', 1], fields)).toBe('true')
        expect(execSync(['_h', op.NULL, op.CALL, 'toString', 1], fields)).toBe('null')
        expect(execSync(['_h', op.STRING, 'string', op.CALL, 'toString', 1], fields)).toBe('string')
        expect(execSync(['_h', op.STRING, '1', op.CALL, 'toInt', 1], fields)).toBe(1)
        expect(execSync(['_h', op.STRING, 'bla', op.CALL, 'toInt', 1], fields)).toBe(null)
        expect(execSync(['_h', op.STRING, '1.2', op.CALL, 'toFloat', 1], fields)).toBe(1.2)
        expect(execSync(['_h', op.STRING, 'bla', op.CALL, 'toFloat', 1], fields)).toBe(null)
        expect(execSync(['_h', op.STRING, 'asd', op.CALL, 'toUUID', 1], fields)).toBe('asd')

        expect(execSync(['_h', op.NULL, op.INTEGER, 1, op.EQ], fields)).toBe(false)
        expect(execSync(['_h', op.NULL, op.INTEGER, 1, op.NOT_EQ], fields)).toBe(true)
    })

    test('error handling', async () => {
        const fields = { properties: { foo: 'bar' } }
        expect(() => execSync([], fields)).toThrowError("Invalid HogQL bytecode, must start with '_h'")
        await expect(execAsync([], fields)).rejects.toThrowError("Invalid HogQL bytecode, must start with '_h'")
        expect(() => execSync(['_h', op.INTEGER, 2, op.INTEGER, 1, 'InvalidOp'], fields)).toThrowError(
            'Unexpected node while running bytecode: InvalidOp'
        )
        expect(() =>
            execSync(['_h', op.STRING, 'another', op.STRING, 'arg', op.CALL, 'invalidFunc', 2], fields)
        ).toThrowError('Unsupported function call: invalidFunc')
        expect(() => execSync(['_h', op.INTEGER], fields)).toThrowError('Unexpected end of bytecode')
        expect(() => execSync(['_h', op.CALL, 'match', 1], fields)).toThrowError(
            'Invalid HogQL bytecode, stack is empty'
        )
        expect(() => execSync(['_h', op.TRUE, op.TRUE, op.NOT], fields)).toThrowError(
            'Invalid bytecode. More than one value left on stack'
        )
        const callSleep = [
            33,
            0.002, // seconds to sleep
            2,
            'sleep',
            1,
        ]
        const bytecode: any[] = ['_h']
        for (let i = 0; i < 200; i++) {
            bytecode.push(...callSleep)
        }
        await expect(execAsync(bytecode, fields)).rejects.toThrowError('Exceeded maximum number of async steps: 100')
    })

    test('should execute user-defined stringify function correctly', async () => {
        const functions = {
            stringify: (arg: any) => {
                if (arg === 1) {
                    return 'one'
                } else if (arg === 2) {
                    return 'two'
                }
                return 'zero'
            },
        }
        expect(execSync(['_h', op.INTEGER, 1, op.CALL, 'stringify', 1], {}, functions)).toBe('one')
        expect(execSync(['_h', op.INTEGER, 2, op.CALL, 'stringify', 1], {}, functions)).toBe('two')
        expect(execSync(['_h', op.STRING, '2', op.CALL, 'stringify', 1], {}, functions)).toBe('zero')
    })

    test('should execute user-defined stringify async function correctly', async () => {
        const functions = {
            stringify: (arg: any): Promise<string> => {
                if (arg === 1) {
                    return Promise.resolve('one')
                } else if (arg === 2) {
                    return Promise.resolve('two')
                }
                return Promise.resolve('zero')
            },
        }
        expect(await execAsync(['_h', op.INTEGER, 1, op.CALL, 'stringify', 1], {}, {}, functions)).toBe('one')
        expect(await execAsync(['_h', op.INTEGER, 2, op.CALL, 'stringify', 1], {}, {}, functions)).toBe('two')
        expect(await execAsync(['_h', op.STRING, '2', op.CALL, 'stringify', 1], {}, {}, functions)).toBe('zero')
    })

    test('bytecode variable assignment', async () => {
        const bytecode = ['_h', op.INTEGER, 2, op.INTEGER, 1, op.PLUS, op.GET_LOCAL, 0, op.RETURN, op.POP]
        expect(execSync(bytecode)).toBe(3)
    })

    test('bytecode if else', async () => {
        const bytecode = [
            '_h',
            op.TRUE,
            op.JUMP_IF_FALSE,
            5,
            op.INTEGER,
            1,
            op.RETURN,
            op.JUMP,
            3,
            op.INTEGER,
            2,
            op.RETURN,
        ]
        expect(execSync(bytecode)).toBe(1)
    })

    test('bytecode while', async () => {
        const bytecode = [
            '_h',
            op.INTEGER,
            0,
            op.INTEGER,
            3,
            op.GET_LOCAL,
            0,
            op.LT,
            op.JUMP_IF_FALSE,
            9,
            op.INTEGER,
            1,
            op.GET_LOCAL,
            0,
            op.PLUS,
            op.SET_LOCAL,
            0,
            op.JUMP,
            -16,
            op.GET_LOCAL,
            0,
            op.RETURN,
            op.POP,
        ]
        expect(execSync(bytecode)).toBe(3)
    })

    test('bytecode functions', async () => {
        const bytecode = [
            '_h',
            op.DECLARE_FN,
            'add',
            2,
            9,
            op.GET_LOCAL,
            0,
            op.GET_LOCAL,
            1,
            op.PLUS,
            op.GET_LOCAL,
            2,
            op.RETURN,
            op.POP,
            op.DECLARE_FN,
            'divide',
            2,
            6,
            op.GET_LOCAL,
            0,
            op.GET_LOCAL,
            1,
            op.DIVIDE,
            op.RETURN,
            op.INTEGER,
            10,
            op.INTEGER,
            1,
            op.INTEGER,
            2,
            op.CALL,
            'add',
            2,
            op.INTEGER,
            100,
            op.INTEGER,
            4,
            op.INTEGER,
            3,
            op.CALL,
            'add',
            2,
            op.PLUS,
            op.PLUS,
            op.CALL,
            'divide',
            2,
            op.RETURN,
        ]
        expect(execSync(bytecode)).toBe(11)
    })

    test('bytecode recursion', async () => {
        const bytecode = [
            '_h',
            op.DECLARE_FN,
            'fibonacci',
            1,
            30,
            op.INTEGER,
            2,
            op.GET_LOCAL,
            0,
            op.LT,
            op.JUMP_IF_FALSE,
            5,
            op.GET_LOCAL,
            0,
            op.RETURN,
            op.JUMP,
            18,
            op.INTEGER,
            2,
            op.GET_LOCAL,
            0,
            op.MINUS,
            op.CALL,
            'fibonacci',
            1,
            op.INTEGER,
            1,
            op.GET_LOCAL,
            0,
            op.MINUS,
            op.CALL,
            'fibonacci',
            1,
            op.PLUS,
            op.RETURN,
            op.INTEGER,
            6,
            op.CALL,
            'fibonacci',
            1,
            op.RETURN,
        ]
        expect(execSync(bytecode)).toBe(8)
    })

    test('sleep', async () => {
        const bytecode = [
            '_h',
            32,
            '!',
            2,
            'print',
            1,
            35,
            32,
            'https://webhook.site/ac6ec36d-60a4-4f86-8389-3b057e029531',
            2,
            'httpGet',
            1,
            35,
            33,
            0.2, // seconds to sleep
            2,
            'sleep',
            1,
            35,
            32,
            'https://webhook.site/ac6ec36d-60a4-4f86-8389-3b057e029531',
            2,
            'httpGet',
            1,
            35,
            33,
            2,
            38,
        ]
        expect(
            await execAsync(
                bytecode,
                {},
                {},
                {
                    httpGet: async (url: string) => {
                        await delay(1)
                        return 'hello ' + url
                    },
                }
            )
        ).toBe(2)
    })

    test('exec stops at async', () => {
        const bytecode = [
            '_h',
            33,
            4.2, // random stack value
            33,
            0.002, // seconds to sleep
            2,
            'sleep',
            1,
        ]
        expect(exec(bytecode)).toEqual({
            asyncFunctionArgs: [0.002],
            asyncFunctionName: 'sleep',
            finished: false,
            result: undefined,
            state: {
                asyncSteps: 1,
                callStack: [],
                declaredFunctions: {},
                ip: 8,
                ops: 3,
                stack: [4.2],
                syncDuration: 0,
            },
        })
    })
    test('exec runs at sync', () => {
        const bytecode = [
            '_h',
            33,
            0.002, // seconds to sleep
            2,
            'toString',
            1,
        ]
        expect(exec(bytecode)).toEqual({
            finished: true,
            result: '0.002',
        })
    })
})
