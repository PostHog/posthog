import { exec, execAsync, execSync, Operation as op } from '../bytecode'

export function delay(ms: number): Promise<void> {
    return new Promise((resolve) => {
        setTimeout(resolve, ms)
    })
}

const map = (obj: Record<string, any>): Map<any, any> => new Map(Object.entries(obj))
const tuple = (array: any[]): any[] => {
    ;(array as any).__isHogTuple = true
    return array
}

describe('HogQL Bytecode', () => {
    test('execution results', async () => {
        const fields = { properties: { foo: 'bar', nullValue: null } }
        const options = { fields }
        expect(execSync(['_h'], options)).toBe(null)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 1, op.PLUS], options)).toBe(3)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 1, op.MINUS], options)).toBe(-1)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 3, op.MULTIPLY], options)).toBe(6)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 3, op.DIVIDE], options)).toBe(1.5)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 3, op.MOD], options)).toBe(1)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 1, op.AND, 2], options)).toBe(true)
        expect(execSync(['_h', op.INTEGER, 0, op.INTEGER, 1, op.OR, 2], options)).toBe(true)
        expect(execSync(['_h', op.INTEGER, 0, op.INTEGER, 1, op.AND, 2], options)).toBe(false)
        expect(execSync(['_h', op.INTEGER, 1, op.INTEGER, 0, op.INTEGER, 1, op.OR, 3], options)).toBe(true)
        expect(execSync(['_h', op.INTEGER, 0, op.INTEGER, 1, op.AND, 2, op.INTEGER, 1, op.AND, 2], options)).toBe(false)
        expect(
            execSync(
                ['_h', op.INTEGER, 2, op.INTEGER, 1, op.OR, 2, op.INTEGER, 2, op.INTEGER, 1, op.OR, 2, op.AND, 2],
                options
            )
        ).toBe(true)
        expect(execSync(['_h', op.TRUE, op.NOT], options)).toBe(false)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 1, op.EQ], options)).toBe(false)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 1, op.NOT_EQ], options)).toBe(true)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 1, op.LT], options)).toBe(true)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 1, op.LT_EQ], options)).toBe(true)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 1, op.GT], options)).toBe(false)
        expect(execSync(['_h', op.INTEGER, 2, op.INTEGER, 1, op.GT_EQ], options)).toBe(false)
        expect(execSync(['_h', op.STRING, 'b', op.STRING, 'a', op.LIKE], options)).toBe(false)
        expect(execSync(['_h', op.STRING, '%a%', op.STRING, 'baa', op.LIKE], options)).toBe(true)
        expect(execSync(['_h', op.STRING, '%x%', op.STRING, 'baa', op.LIKE], options)).toBe(false)
        expect(execSync(['_h', op.STRING, '%A%', op.STRING, 'baa', op.ILIKE], options)).toBe(true)
        expect(execSync(['_h', op.STRING, '%C%', op.STRING, 'baa', op.ILIKE], options)).toBe(false)
        expect(execSync(['_h', op.STRING, 'b', op.STRING, 'a', op.NOT_LIKE], options)).toBe(true)
        expect(execSync(['_h', op.STRING, 'b', op.STRING, 'a', op.NOT_ILIKE], options)).toBe(true)
        expect(execSync(['_h', op.STRING, 'car', op.STRING, 'a', op.IN], options)).toBe(true)
        expect(execSync(['_h', op.STRING, 'car', op.STRING, 'a', op.NOT_IN], options)).toBe(false)
        expect(execSync(['_h', op.STRING, '.*', op.STRING, 'a', op.REGEX], options)).toBe(true)
        expect(execSync(['_h', op.STRING, 'b', op.STRING, 'a', op.REGEX], options)).toBe(false)
        expect(execSync(['_h', op.STRING, '.*', op.STRING, 'a', op.NOT_REGEX], options)).toBe(false)
        expect(execSync(['_h', op.STRING, 'b', op.STRING, 'a', op.NOT_REGEX], options)).toBe(true)
        expect(execSync(['_h', op.STRING, '.*', op.STRING, 'kala', op.IREGEX], options)).toBe(true)
        expect(execSync(['_h', op.STRING, 'b', op.STRING, 'kala', op.IREGEX], options)).toBe(false)
        expect(execSync(['_h', op.STRING, 'AL', op.STRING, 'kala', op.IREGEX], options)).toBe(true)
        expect(execSync(['_h', op.STRING, '.*', op.STRING, 'kala', op.NOT_IREGEX], options)).toBe(false)
        expect(execSync(['_h', op.STRING, 'b', op.STRING, 'kala', op.NOT_IREGEX], options)).toBe(true)
        expect(execSync(['_h', op.STRING, 'AL', op.STRING, 'kala', op.NOT_IREGEX], options)).toBe(false)
        expect(execSync(['_h', op.STRING, 'bla', op.STRING, 'properties', op.FIELD, 2], options)).toBe(null)
        expect(execSync(['_h', op.STRING, 'foo', op.STRING, 'properties', op.FIELD, 2], options)).toBe('bar')
        expect(
            execSync(
                ['_h', op.FALSE, op.STRING, 'foo', op.STRING, 'properties', op.FIELD, 2, op.CALL, 'ifNull', 2],
                options
            )
        ).toBe('bar')
        expect(
            execSync(
                ['_h', op.FALSE, op.STRING, 'nullValue', op.STRING, 'properties', op.FIELD, 2, op.CALL, 'ifNull', 2],
                options
            )
        ).toBe(false)
        expect(execSync(['_h', op.STRING, 'another', op.STRING, 'arg', op.CALL, 'concat', 2], options)).toBe(
            'arganother'
        )
        expect(execSync(['_h', op.NULL, op.INTEGER, 1, op.CALL, 'concat', 2], options)).toBe('1')
        expect(execSync(['_h', op.FALSE, op.TRUE, op.CALL, 'concat', 2], options)).toBe('truefalse')
        expect(execSync(['_h', op.STRING, 'e.*', op.STRING, 'test', op.CALL, 'match', 2], options)).toBe(true)
        expect(execSync(['_h', op.STRING, '^e.*', op.STRING, 'test', op.CALL, 'match', 2], options)).toBe(false)
        expect(execSync(['_h', op.STRING, 'x.*', op.STRING, 'test', op.CALL, 'match', 2], options)).toBe(false)
        expect(execSync(['_h', op.INTEGER, 1, op.CALL, 'toString', 1], options)).toBe('1')
        expect(execSync(['_h', op.FLOAT, 1.5, op.CALL, 'toString', 1], options)).toBe('1.5')
        expect(execSync(['_h', op.TRUE, op.CALL, 'toString', 1], options)).toBe('true')
        expect(execSync(['_h', op.NULL, op.CALL, 'toString', 1], options)).toBe('null')
        expect(execSync(['_h', op.STRING, 'string', op.CALL, 'toString', 1], options)).toBe('string')
        expect(execSync(['_h', op.STRING, '1', op.CALL, 'toInt', 1], options)).toBe(1)
        expect(execSync(['_h', op.STRING, 'bla', op.CALL, 'toInt', 1], options)).toBe(null)
        expect(execSync(['_h', op.STRING, '1.2', op.CALL, 'toFloat', 1], options)).toBe(1.2)
        expect(execSync(['_h', op.STRING, 'bla', op.CALL, 'toFloat', 1], options)).toBe(null)
        expect(execSync(['_h', op.STRING, 'asd', op.CALL, 'toUUID', 1], options)).toBe('asd')

        expect(execSync(['_h', op.NULL, op.INTEGER, 1, op.EQ], options)).toBe(false)
        expect(execSync(['_h', op.NULL, op.INTEGER, 1, op.NOT_EQ], options)).toBe(true)
    })

    test('error handling', async () => {
        const fields = { properties: { foo: 'bar' } }
        const options = { fields }
        expect(() => execSync([], options)).toThrowError("Invalid HogQL bytecode, must start with '_h'")
        await expect(execAsync([], options)).rejects.toThrowError("Invalid HogQL bytecode, must start with '_h'")
        expect(() => execSync(['_h', op.INTEGER, 2, op.INTEGER, 1, 'InvalidOp'], options)).toThrowError(
            'Unexpected node while running bytecode: InvalidOp'
        )
        expect(() =>
            execSync(['_h', op.STRING, 'another', op.STRING, 'arg', op.CALL, 'invalidFunc', 2], options)
        ).toThrowError('Unsupported function call: invalidFunc')
        expect(() => execSync(['_h', op.INTEGER], options)).toThrowError('Unexpected end of bytecode')
        expect(() => execSync(['_h', op.CALL, 'match', 1], options)).toThrowError(
            'Invalid HogQL bytecode, stack is empty'
        )
        expect(() => execSync(['_h', op.TRUE, op.TRUE, op.NOT], options)).toThrowError(
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
        await expect(execAsync(bytecode, options)).rejects.toThrowError('Exceeded maximum number of async steps: 100')
        await expect(execAsync(bytecode, { ...options, maxAsyncSteps: 55 })).rejects.toThrowError(
            'Exceeded maximum number of async steps: 55'
        )
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
        expect(execSync(['_h', op.INTEGER, 1, op.CALL, 'stringify', 1], { functions })).toBe('one')
        expect(execSync(['_h', op.INTEGER, 2, op.CALL, 'stringify', 1], { functions })).toBe('two')
        expect(execSync(['_h', op.STRING, '2', op.CALL, 'stringify', 1], { functions })).toBe('zero')
    })

    test('should execute user-defined stringify async function correctly', async () => {
        const asyncFunctions = {
            stringify: (arg: any): Promise<string> => {
                if (arg === 1) {
                    return Promise.resolve('one')
                } else if (arg === 2) {
                    return Promise.resolve('two')
                }
                return Promise.resolve('zero')
            },
        }
        expect(await execAsync(['_h', op.INTEGER, 1, op.CALL, 'stringify', 1], { asyncFunctions })).toBe('one')
        expect(await execAsync(['_h', op.INTEGER, 2, op.CALL, 'stringify', 1], { asyncFunctions })).toBe('two')
        expect(await execAsync(['_h', op.STRING, '2', op.CALL, 'stringify', 1], { asyncFunctions })).toBe('zero')
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
            await execAsync(bytecode, {
                asyncFunctions: {
                    httpGet: async (url: string) => {
                        await delay(1)
                        return 'hello ' + url
                    },
                },
            })
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
    test('test bytecode dicts', () => {
        // return {};
        expect(exec(['_h', op.DICT, 0, op.RETURN]).result).toEqual(map({}))

        // return {'key': 'value'};
        expect(exec(['_h', op.STRING, 'key', op.STRING, 'value', op.DICT, 1, op.RETURN]).result).toEqual(
            map({
                key: 'value',
            })
        )

        // return {'key': 'value', 'other': 'thing'};
        expect(
            exec([
                '_h',
                op.STRING,
                'key',
                op.STRING,
                'value',
                op.STRING,
                'other',
                op.STRING,
                'thing',
                op.DICT,
                2,
                op.RETURN,
            ]).result
        ).toEqual(map({ key: 'value', other: 'thing' }))

        // return {'key': {'otherKey': 'value'}};
        expect(
            exec(['_h', op.STRING, 'key', op.STRING, 'otherKey', op.STRING, 'value', op.DICT, 1, op.DICT, 1, op.RETURN])
                .result
        ).toEqual(map({ key: map({ otherKey: 'value' }) }))

        // return {key: 'value'};
        expect(exec(['_h', op.STRING, 'key', op.FIELD, 1, op.STRING, 'value', op.DICT, 1, op.RETURN]).result).toEqual(
            new Map([[null, 'value']])
        )

        // var key := 3; return {key: 'value'};
        expect(
            exec(['_h', op.INTEGER, 3, op.GET_LOCAL, 0, op.STRING, 'value', op.DICT, 1, op.RETURN, op.POP]).result
        ).toEqual(new Map([[3, 'value']]))

        // return {'key': 'value'}.key;
        expect(
            exec(['_h', op.STRING, 'key', op.STRING, 'value', op.DICT, 1, op.STRING, 'key', op.GET_PROPERTY, op.RETURN])
                .result
        ).toEqual('value')

        // return {'key': 'value'}['key'];
        expect(
            exec(['_h', op.STRING, 'key', op.STRING, 'value', op.DICT, 1, op.STRING, 'key', op.GET_PROPERTY, op.RETURN])
                .result
        ).toEqual('value')

        // return {'key': {'otherKey': 'value'}}.key.otherKey;
        expect(
            exec([
                '_h',
                op.STRING,
                'key',
                op.STRING,
                'otherKey',
                op.STRING,
                'value',
                op.DICT,
                1,
                op.DICT,
                1,
                op.STRING,
                'key',
                op.GET_PROPERTY,
                op.STRING,
                'otherKey',
                op.GET_PROPERTY,
                op.RETURN,
            ]).result
        ).toEqual('value')

        // return {'key': {'otherKey': 'value'}}['key'].otherKey;
        expect(
            exec([
                '_h',
                op.STRING,
                'key',
                op.STRING,
                'otherKey',
                op.STRING,
                'value',
                op.DICT,
                1,
                op.DICT,
                1,
                op.STRING,
                'key',
                op.GET_PROPERTY,
                op.STRING,
                'otherKey',
                op.GET_PROPERTY,
                op.RETURN,
            ]).result
        ).toEqual('value')
    })

    test('test bytecode arrays', () => {
        // return [];
        expect(exec(['_h', op.ARRAY, 0, op.RETURN]).result).toEqual([])

        // return [1, 2, 3];
        expect(exec(['_h', op.INTEGER, 1, op.INTEGER, 2, op.INTEGER, 3, op.ARRAY, 3, op.RETURN]).result).toEqual([
            1, 2, 3,
        ])

        // return [1, '2', 3];
        expect(exec(['_h', op.INTEGER, 1, op.STRING, '2', op.INTEGER, 3, op.ARRAY, 3, op.RETURN]).result).toEqual([
            1,
            '2',
            3,
        ])

        // return [1, [2, 3], 4];
        expect(
            exec([
                '_h',
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.INTEGER,
                3,
                op.ARRAY,
                2,
                op.INTEGER,
                4,
                op.ARRAY,
                3,
                op.RETURN,
            ]).result
        ).toEqual([1, [2, 3], 4])

        // return [1, [2, [3, 4]], 5];
        expect(
            exec([
                '_h',
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.INTEGER,
                3,
                op.INTEGER,
                4,
                op.ARRAY,
                2,
                op.ARRAY,
                2,
                op.INTEGER,
                5,
                op.ARRAY,
                3,
                op.RETURN,
            ]).result
        ).toEqual([1, [2, [3, 4]], 5])

        // var a := [1, 2, 3]; return a[1];
        expect(
            exec([
                '_h',
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.INTEGER,
                3,
                op.ARRAY,
                3,
                op.GET_LOCAL,
                0,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.RETURN,
                op.POP,
            ]).result
        ).toEqual(2)

        // return [1, 2, 3][1];
        expect(
            exec([
                '_h',
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.INTEGER,
                3,
                op.ARRAY,
                3,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.RETURN,
            ]).result
        ).toEqual(2)

        // return [1, [2, [3, 4]], 5][1][1][1];
        expect(
            exec([
                '_h',
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.INTEGER,
                3,
                op.INTEGER,
                4,
                op.ARRAY,
                2,
                op.ARRAY,
                2,
                op.INTEGER,
                5,
                op.ARRAY,
                3,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.RETURN,
            ]).result
        ).toEqual(4)

        // return [1, [2, [3, 4]], 5][1][1][1] + 1;
        expect(
            exec([
                '_h',
                op.INTEGER,
                1,
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.INTEGER,
                3,
                op.INTEGER,
                4,
                op.ARRAY,
                2,
                op.ARRAY,
                2,
                op.INTEGER,
                5,
                op.ARRAY,
                3,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.PLUS,
                op.RETURN,
            ]).result
        ).toEqual(5)

        // return [1, [2, [3, 4]], 5].1.1.1;
        expect(
            exec([
                '_h',
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.INTEGER,
                3,
                op.INTEGER,
                4,
                op.ARRAY,
                2,
                op.ARRAY,
                2,
                op.INTEGER,
                5,
                op.ARRAY,
                3,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.RETURN,
            ]).result
        ).toEqual(4)
    })

    test('test bytecode tuples', () => {
        // return (1, 2, 3);
        expect(exec(['_h', op.INTEGER, 1, op.INTEGER, 2, op.INTEGER, 3, op.TUPLE, 3, op.RETURN]).result).toEqual(
            tuple([1, 2, 3])
        )

        // return (1, '2', 3);
        expect(exec(['_h', op.INTEGER, 1, op.STRING, '2', op.INTEGER, 3, op.TUPLE, 3, op.RETURN]).result).toEqual(
            tuple([1, '2', 3])
        )

        // return (1, (2, 3), 4);
        expect(
            exec([
                '_h',
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.INTEGER,
                3,
                op.TUPLE,
                2,
                op.INTEGER,
                4,
                op.TUPLE,
                3,
                op.RETURN,
            ]).result
        ).toEqual(tuple([1, tuple([2, 3]), 4]))

        // return (1, (2, (3, 4)), 5);
        expect(
            exec([
                '_h',
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.INTEGER,
                3,
                op.INTEGER,
                4,
                op.TUPLE,
                2,
                op.TUPLE,
                2,
                op.INTEGER,
                5,
                op.TUPLE,
                3,
                op.RETURN,
            ]).result
        ).toEqual(tuple([1, tuple([2, tuple([3, 4])]), 5]))

        // var a := (1, 2, 3); return a[1];
        expect(
            exec([
                '_h',
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.INTEGER,
                3,
                op.TUPLE,
                3,
                op.GET_LOCAL,
                0,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.RETURN,
                op.POP,
            ]).result
        ).toEqual(2)

        // return (1, (2, (3, 4)), 5)[1][1][1];
        expect(
            exec([
                '_h',
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.INTEGER,
                3,
                op.INTEGER,
                4,
                op.TUPLE,
                2,
                op.TUPLE,
                2,
                op.INTEGER,
                5,
                op.TUPLE,
                3,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.RETURN,
            ]).result
        ).toEqual(4)

        // return (1, (2, (3, 4)), 5).1.1.1;
        expect(
            exec([
                '_h',
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.INTEGER,
                3,
                op.INTEGER,
                4,
                op.TUPLE,
                2,
                op.TUPLE,
                2,
                op.INTEGER,
                5,
                op.TUPLE,
                3,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.RETURN,
            ]).result
        ).toEqual(4)

        // return (1, (2, (3, 4)), 5)[1][1][1] + 1;
        expect(
            exec([
                '_h',
                op.INTEGER,
                1,
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.INTEGER,
                3,
                op.INTEGER,
                4,
                op.TUPLE,
                2,
                op.TUPLE,
                2,
                op.INTEGER,
                5,
                op.TUPLE,
                3,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.PLUS,
                op.RETURN,
            ]).result
        ).toEqual(5)
    })

    test('test bytecode nested', () => {
        // var r := [1, 2, {'d': (1, 3, 42, 6)}]; return r.2.d.1;
        expect(
            exec([
                '_h',
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.STRING,
                'd',
                op.INTEGER,
                1,
                op.INTEGER,
                3,
                op.INTEGER,
                42,
                op.INTEGER,
                6,
                op.TUPLE,
                4,
                op.DICT,
                1,
                op.ARRAY,
                3,
                op.GET_LOCAL,
                0,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.STRING,
                'd',
                op.GET_PROPERTY,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.RETURN,
                op.POP,
            ]).result
        ).toEqual(3)

        // var r := [1, 2, {'d': (1, 3, 42, 6)}]; return r[2].d[2];
        expect(
            exec([
                '_h',
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.STRING,
                'd',
                op.INTEGER,
                1,
                op.INTEGER,
                3,
                op.INTEGER,
                42,
                op.INTEGER,
                6,
                op.TUPLE,
                4,
                op.DICT,
                1,
                op.ARRAY,
                3,
                op.GET_LOCAL,
                0,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.STRING,
                'd',
                op.GET_PROPERTY,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.RETURN,
                op.POP,
            ]).result
        ).toEqual(42)

        // var r := [1, 2, {'d': (1, 3, 42, 6)}]; return r.2['d'][3];
        expect(
            exec([
                '_h',
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.STRING,
                'd',
                op.INTEGER,
                1,
                op.INTEGER,
                3,
                op.INTEGER,
                42,
                op.INTEGER,
                6,
                op.TUPLE,
                4,
                op.DICT,
                1,
                op.ARRAY,
                3,
                op.GET_LOCAL,
                0,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.STRING,
                'd',
                op.GET_PROPERTY,
                op.INTEGER,
                3,
                op.GET_PROPERTY,
                op.RETURN,
                op.POP,
            ]).result
        ).toEqual(6)

        // var r := {'d': (1, 3, 42, 6)}; return r.d.1;
        expect(
            exec([
                '_h',
                op.STRING,
                'd',
                op.INTEGER,
                1,
                op.INTEGER,
                3,
                op.INTEGER,
                42,
                op.INTEGER,
                6,
                op.TUPLE,
                4,
                op.DICT,
                1,
                op.GET_LOCAL,
                0,
                op.STRING,
                'd',
                op.GET_PROPERTY,
                op.INTEGER,
                1,
                op.GET_PROPERTY,
                op.RETURN,
                op.POP,
            ]).result
        ).toEqual(3)
    })

    test('test bytecode nested modify', () => {
        // var r := [1, 2, {'d': [1, 3, 42, 3]}];
        // r.2.d.2 := 3;
        // return r.2.d.2;
        expect(
            exec([
                '_h',
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.STRING,
                'd',
                op.INTEGER,
                1,
                op.INTEGER,
                3,
                op.INTEGER,
                42,
                op.INTEGER,
                3,
                op.ARRAY,
                4,
                op.DICT,
                1,
                op.ARRAY,
                3,
                op.GET_LOCAL,
                0,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.STRING,
                'd',
                op.GET_PROPERTY,
                op.INTEGER,
                2,
                op.INTEGER,
                3,
                op.SET_PROPERTY,
                op.GET_LOCAL,
                0,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.STRING,
                'd',
                op.GET_PROPERTY,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.RETURN,
                op.POP,
            ]).result
        ).toEqual(3)

        // var r := [1, 2, {'d': [1, 3, 42, 3]}];
        // r[2].d[2] := 3;
        // return r[2].d[2];
        expect(
            exec([
                '_h',
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.STRING,
                'd',
                op.INTEGER,
                1,
                op.INTEGER,
                3,
                op.INTEGER,
                42,
                op.INTEGER,
                3,
                op.ARRAY,
                4,
                op.DICT,
                1,
                op.ARRAY,
                3,
                op.GET_LOCAL,
                0,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.STRING,
                'd',
                op.GET_PROPERTY,
                op.INTEGER,
                2,
                op.INTEGER,
                3,
                op.SET_PROPERTY,
                op.GET_LOCAL,
                0,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.STRING,
                'd',
                op.GET_PROPERTY,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.RETURN,
                op.POP,
            ]).result
        ).toEqual(3)

        // var r := [1, 2, {'d': [1, 3, 42, 3]}];
        // r[2].c := [666];
        // return r[2];
        expect(
            exec([
                '_h',
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.STRING,
                'd',
                op.INTEGER,
                1,
                op.INTEGER,
                3,
                op.INTEGER,
                42,
                op.INTEGER,
                3,
                op.ARRAY,
                4,
                op.DICT,
                1,
                op.ARRAY,
                3,
                op.GET_LOCAL,
                0,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.STRING,
                'c',
                op.INTEGER,
                666,
                op.ARRAY,
                1,
                op.SET_PROPERTY,
                op.GET_LOCAL,
                0,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.RETURN,
                op.POP,
            ]).result
        ).toEqual(map({ d: [1, 3, 42, 3], c: [666] }))

        // var r := [1, 2, {'d': [1, 3, 42, 3]}];
        // r[2].d[2] := 3;
        // return r[2].d;
        expect(
            exec([
                '_h',
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.STRING,
                'd',
                op.INTEGER,
                1,
                op.INTEGER,
                3,
                op.INTEGER,
                42,
                op.INTEGER,
                3,
                op.ARRAY,
                4,
                op.DICT,
                1,
                op.ARRAY,
                3,
                op.GET_LOCAL,
                0,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.STRING,
                'd',
                op.GET_PROPERTY,
                op.INTEGER,
                2,
                op.INTEGER,
                3,
                op.SET_PROPERTY,
                op.GET_LOCAL,
                0,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.STRING,
                'd',
                op.GET_PROPERTY,
                op.RETURN,
                op.POP,
            ]).result
        ).toEqual([1, 3, 3, 3])

        // var r := [1, 2, {'d': [1, 3, 42, 3]}];
        // r.2['d'] := ['a', 'b', 'c', 'd'];
        // return r[2].d[2];
        expect(
            exec([
                '_h',
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.STRING,
                'd',
                op.INTEGER,
                1,
                op.INTEGER,
                3,
                op.INTEGER,
                42,
                op.INTEGER,
                3,
                op.ARRAY,
                4,
                op.DICT,
                1,
                op.ARRAY,
                3,
                op.GET_LOCAL,
                0,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.STRING,
                'd',
                op.STRING,
                'a',
                op.STRING,
                'b',
                op.STRING,
                'c',
                op.STRING,
                'd',
                op.ARRAY,
                4,
                op.SET_PROPERTY,
                op.GET_LOCAL,
                0,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.STRING,
                'd',
                op.GET_PROPERTY,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.RETURN,
                op.POP,
            ]).result
        ).toEqual('c')

        // var r := [1, 2, {'d': [1, 3, 42, 3]}];
        // var g := 'd';
        // r.2[g] := ['a', 'b', 'c', 'd'];
        // return r[2].d[2];
        expect(
            exec([
                '_h',
                op.INTEGER,
                1,
                op.INTEGER,
                2,
                op.STRING,
                'd',
                op.INTEGER,
                1,
                op.INTEGER,
                3,
                op.INTEGER,
                42,
                op.INTEGER,
                3,
                op.ARRAY,
                4,
                op.DICT,
                1,
                op.ARRAY,
                3,
                op.STRING,
                'd',
                op.GET_LOCAL,
                0,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.GET_LOCAL,
                1,
                op.STRING,
                'a',
                op.STRING,
                'b',
                op.STRING,
                'c',
                op.STRING,
                'd',
                op.ARRAY,
                4,
                op.SET_PROPERTY,
                op.GET_LOCAL,
                0,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.STRING,
                'd',
                op.GET_PROPERTY,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.RETURN,
                op.POP,
                op.POP,
            ]).result
        ).toEqual('c')
    })

    test('test bytecode nested modify dict', () => {
        // let event := {
        //     'event': '$pageview',
        //     'properties': {
        //         '$browser': 'Chrome',
        //         '$os': 'Windows'
        //     }
        // };
        // event['properties']['$browser'] := 'Firefox';
        // return event;
        expect(
            exec([
                '_h',
                op.STRING,
                'event',
                op.STRING,
                '$pageview',
                op.STRING,
                'properties',
                op.STRING,
                '$browser',
                op.STRING,
                'Chrome',
                op.STRING,
                '$os',
                op.STRING,
                'Windows',
                op.DICT,
                2,
                op.DICT,
                2,
                op.GET_LOCAL,
                0,
                op.STRING,
                'properties',
                op.GET_PROPERTY,
                op.STRING,
                '$browser',
                op.STRING,
                'Firefox',
                op.SET_PROPERTY,
                op.GET_LOCAL,
                0,
                op.RETURN,
                op.POP,
            ]).result
        ).toEqual(map({ event: '$pageview', properties: map({ $browser: 'Firefox', $os: 'Windows' }) }))

        // let event := {
        //     'event': '$pageview',
        //     'properties': {
        //         '$browser': 'Chrome',
        //         '$os': 'Windows'
        //     }
        // };
        // event.properties.$browser := 'Firefox';
        // return event;
        expect(
            exec([
                '_h',
                op.STRING,
                'event',
                op.STRING,
                '$pageview',
                op.STRING,
                'properties',
                op.STRING,
                '$browser',
                op.STRING,
                'Chrome',
                op.STRING,
                '$os',
                op.STRING,
                'Windows',
                op.DICT,
                2,
                op.DICT,
                2,
                op.GET_LOCAL,
                0,
                op.STRING,
                'properties',
                op.GET_PROPERTY,
                op.STRING,
                '$browser',
                op.STRING,
                'Firefox',
                op.SET_PROPERTY,
                op.GET_LOCAL,
                0,
                op.RETURN,
                op.POP,
            ]).result
        ).toEqual(map({ event: '$pageview', properties: map({ $browser: 'Firefox', $os: 'Windows' }) }))

        // let event := {
        //     'event': '$pageview',
        //     'properties': {
        //         '$browser': 'Chrome',
        //         '$os': 'Windows'
        //     }
        // };
        // let config := {};
        // return event;
        expect(
            exec([
                '_h',
                op.STRING,
                'event',
                op.STRING,
                '$pageview',
                op.STRING,
                'properties',
                op.STRING,
                '$browser',
                op.STRING,
                'Chrome',
                op.STRING,
                '$os',
                op.STRING,
                'Windows',
                op.DICT,
                2,
                op.DICT,
                2,
                op.DICT,
                0,
                op.GET_LOCAL,
                0,
                op.RETURN,
                op.POP,
                op.POP,
            ]).result
        ).toEqual(map({ event: '$pageview', properties: map({ $browser: 'Chrome', $os: 'Windows' }) }))
    })

    test('test bytecode json', () => {
        const dict = [
            op.STRING,
            'event',
            op.STRING,
            '$pageview',
            op.STRING,
            'properties',
            op.STRING,
            '$browser',
            op.STRING,
            'Chrome',
            op.STRING,
            '$os',
            op.STRING,
            'Windows',
            op.DICT,
            2,
            op.DICT,
            2,
        ]
        expect(execSync(['_h', op.STRING, '[1,2,3]', op.CALL, 'jsonParse', 1])).toEqual([1, 2, 3])
        expect(execSync(['_h', ...dict, op.CALL, 'jsonStringify', 1])).toEqual(
            '{"event":"$pageview","properties":{"$browser":"Chrome","$os":"Windows"}}'
        )
        expect(execSync(['_h', op.INTEGER, 2, ...dict, op.CALL, 'jsonStringify', 2])).toEqual(
            JSON.stringify({ event: '$pageview', properties: { $browser: 'Chrome', $os: 'Windows' } }, null, 2)
        )
    })
})
