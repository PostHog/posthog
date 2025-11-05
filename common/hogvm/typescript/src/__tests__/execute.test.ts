import RE2 from 're2'

import { exec, execAsync, execSync } from '../execute'
import { Operation as op } from '../operation'
import { BytecodeEntry } from '../types'
import { UncaughtHogVMException } from '../utils'

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

describe('hogvm execute', () => {
    test('execution results', async () => {
        const globals = { properties: { foo: 'bar', nullValue: null } }
        const options = {
            globals,
            external: {
                regex: {
                    match: (regex: string, value: string) => new RE2(regex).test(value),
                },
            },
        }
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

        expect(execSync(['_h', op.STRING, '(?i)AL', op.STRING, 'kala', op.REGEX], options)).toBe(true)
        expect(execSync(['_h', op.STRING, '(?i)AL', op.STRING, 'kala', op.IREGEX], options)).toBe(true)
        expect(execSync(['_h', op.STRING, '(?-i)AL', op.STRING, 'kala', op.REGEX], options)).toBe(false)
        expect(execSync(['_h', op.STRING, '(?-i)AL', op.STRING, 'kala', op.IREGEX], options)).toBe(false)

        expect(execSync(['_h', op.STRING, 'bla', op.STRING, 'properties', op.GET_GLOBAL, 2], options)).toBe(null)
        expect(execSync(['_h', op.STRING, 'foo', op.STRING, 'properties', op.GET_GLOBAL, 2], options)).toBe('bar')
        expect(execSync(['_h', op.STRING, 'another', op.STRING, 'arg', op.CALL_GLOBAL, 'concat', 2], options)).toBe(
            'arganother'
        )
        expect(execSync(['_h', op.NULL, op.INTEGER, 1, op.CALL_GLOBAL, 'concat', 2], options)).toBe('1')
        expect(execSync(['_h', op.FALSE, op.TRUE, op.CALL_GLOBAL, 'concat', 2], options)).toBe('truefalse')
        expect(execSync(['_h', op.STRING, 'e.*', op.STRING, 'test', op.CALL_GLOBAL, 'match', 2], options)).toBe(true)
        expect(execSync(['_h', op.STRING, '^e.*', op.STRING, 'test', op.CALL_GLOBAL, 'match', 2], options)).toBe(false)
        expect(execSync(['_h', op.STRING, 'x.*', op.STRING, 'test', op.CALL_GLOBAL, 'match', 2], options)).toBe(false)

        // Test the issue with .+ regex and null values (representing non-existent properties)
        expect(execSync(['_h', op.STRING, '.+', op.STRING, '', op.CALL_GLOBAL, 'match', 2], options)).toBe(false) // empty string should not match .+
        expect(execSync(['_h', op.STRING, '.+', op.NULL, op.CALL_GLOBAL, 'match', 2], options)).toBe(false) // null should not match .+ - this should now work correctly
        expect(execSync(['_h', op.INTEGER, 1, op.CALL_GLOBAL, 'toString', 1], options)).toBe('1')
        expect(execSync(['_h', op.FLOAT, 1.5, op.CALL_GLOBAL, 'toString', 1], options)).toBe('1.5')
        expect(execSync(['_h', op.TRUE, op.CALL_GLOBAL, 'toString', 1], options)).toBe('true')
        expect(execSync(['_h', op.NULL, op.CALL_GLOBAL, 'toString', 1], options)).toBe('null')
        expect(execSync(['_h', op.STRING, 'string', op.CALL_GLOBAL, 'toString', 1], options)).toBe('string')
        expect(execSync(['_h', op.STRING, '1', op.CALL_GLOBAL, 'toInt', 1], options)).toBe(1)
        expect(execSync(['_h', op.STRING, 'bla', op.CALL_GLOBAL, 'toInt', 1], options)).toBe(null)
        expect(execSync(['_h', op.STRING, '1.2', op.CALL_GLOBAL, 'toFloat', 1], options)).toBe(1.2)
        expect(execSync(['_h', op.STRING, 'bla', op.CALL_GLOBAL, 'toFloat', 1], options)).toBe(null)
        expect(execSync(['_h', op.STRING, 'asd', op.CALL_GLOBAL, 'toUUID', 1], options)).toBe('asd')

        expect(execSync(['_h', op.NULL, op.INTEGER, 1, op.EQ], options)).toBe(false)
        expect(execSync(['_h', op.NULL, op.INTEGER, 1, op.NOT_EQ], options)).toBe(true)
    })

    test('error handling', async () => {
        const globals = { properties: { foo: 'bar' } }
        const options = { globals }
        expect(() => execSync([], options)).toThrow("Invalid HogQL bytecode, must start with '_H'")
        await expect(execAsync([], options)).rejects.toThrow("Invalid HogQL bytecode, must start with '_H'")

        expect(() => execSync(['_h', op.INTEGER, 2, op.INTEGER, 1, 'InvalidOp'], options)).toThrow(
            'Unexpected node while running bytecode in chunk "root": InvalidOp'
        )
        expect(() =>
            execSync(['_h', op.STRING, 'another', op.STRING, 'arg', op.CALL_GLOBAL, 'invalidFunc', 2], options)
        ).toThrow('Unsupported function call: invalidFunc')
        expect(() => execSync(['_h', op.INTEGER], options)).toThrow('Unexpected end of bytecode')
        expect(() => execSync(['_h', op.CALL_GLOBAL, 'match', 1], options)).toThrow('Not enough arguments on the stack')

        expect(() => execSync(['_H', 1, op.INTEGER, 2, op.INTEGER, 1, 'InvalidOp'], options)).toThrow(
            'Unexpected node while running bytecode in chunk "root": InvalidOp'
        )
        expect(() =>
            execSync(['_H', 1, op.STRING, 'another', op.STRING, 'arg', op.CALL_GLOBAL, 'invalidFunc', 2], options)
        ).toThrow('Unsupported function call: invalidFunc')
        expect(() => execSync(['_H', 1, op.INTEGER], options)).toThrow('Unexpected end of bytecode')
        expect(() => execSync(['_H', 1, op.CALL_GLOBAL, 'match', 1], options)).toThrow(
            'Not enough arguments on the stack'
        )
    })

    test('async limits', async () => {
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
        await expect(execAsync(bytecode)).rejects.toThrow('Exceeded maximum number of async steps: 100')
        await expect(execAsync(bytecode, { maxAsyncSteps: 55 })).rejects.toThrow(
            'Exceeded maximum number of async steps: 55'
        )
    })

    test('call arg limits', async () => {
        const bytecode = ['_h', 33, 0.002, 2, 'sleep', 301]
        expect(() => execSync(bytecode)).toThrow('Not enough arguments on the stack')

        const bytecode2: any[] = ['_h']
        for (let i = 0; i < 301; i++) {
            bytecode2.push(33, 0.002)
        }
        bytecode2.push(2, 'sleep', 301)
        expect(() => execSync(bytecode2)).toThrow('Too many arguments')
    })

    test('memory limits 1', async () => {
        // let string := 'banana'
        // for (let i := 0; i < 100; i := i + 1) {
        //   string := string || string
        // }
        const bytecode: any[] = [
            '_h',
            32,
            'banana',
            33,
            0,
            33,
            100,
            36,
            1,
            15,
            40,
            18,
            36,
            0,
            36,
            0,
            2,
            'concat',
            2,
            37,
            0,
            33,
            1,
            36,
            1,
            6,
            37,
            1,
            39,
            -25,
            35,
            35,
        ]

        await expect(execAsync(bytecode)).rejects.toThrow(
            'Memory limit of 67108864 bytes exceeded. Tried to allocate 75497504 bytes.'
        )
    })

    test('memory limits 2', async () => {
        // // Printing recursive objects.
        // let obj := {'key': 'value', 'key2': 'value2'}
        // let str := 'na'
        // for (let i := 0; i < 10000; i := i + 1) {
        //   if (i < 16) {
        //     str := str || str
        //   }
        //   obj[f'key_{i}'] := {
        //     'wasted': 'memory: ' || str || ' batman!',
        //     'something': obj,  // something links to obj
        //   }
        // }
        const bytecode: any[] = [
            '_h',
            32,
            'key',
            32,
            'value',
            32,
            'key2',
            32,
            'value2',
            42,
            2,
            32,
            'na',
            33,
            0,
            33,
            10000,
            36,
            2,
            15,
            40,
            52,
            33,
            16,
            36,
            2,
            15,
            40,
            9,
            36,
            1,
            36,
            1,
            2,
            'concat',
            2,
            37,
            1,
            36,
            0,
            36,
            2,
            32,
            'key_',
            2,
            'concat',
            2,
            32,
            'wasted',
            32,
            ' batman!',
            36,
            1,
            32,
            'memory: ',
            2,
            'concat',
            3,
            32,
            'something',
            36,
            0,
            42,
            2,
            46,
            33,
            1,
            36,
            2,
            6,
            37,
            2,
            39,
            -59,
            35,
            35,
            35,
        ]

        await expect(execAsync(bytecode)).rejects.toThrow(
            'Memory limit of 67108864 bytes exceeded. Tried to allocate 67155164 bytes.'
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
        expect(execSync(['_h', op.INTEGER, 1, op.CALL_GLOBAL, 'stringify', 1], { functions })).toBe('one')
        expect(execSync(['_h', op.INTEGER, 2, op.CALL_GLOBAL, 'stringify', 1], { functions })).toBe('two')
        expect(execSync(['_h', op.STRING, '2', op.CALL_GLOBAL, 'stringify', 1], { functions })).toBe('zero')
    })

    test('version 0 and 1', async () => {
        expect(execSync(['_h', op.STRING, '1', op.STRING, '2', op.CALL_GLOBAL, 'concat', 2, op.RETURN])).toBe('21')
        expect(execSync(['_H', 1, op.STRING, '1', op.STRING, '2', op.CALL_GLOBAL, 'concat', 2, op.RETURN])).toBe('12')
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
        expect(
            (await execAsync(['_h', op.INTEGER, 1, op.CALL_GLOBAL, 'stringify', 1, op.RETURN], { asyncFunctions }))
                .result
        ).toBe('one')
        expect(
            (await execAsync(['_h', op.INTEGER, 2, op.CALL_GLOBAL, 'stringify', 1, op.RETURN], { asyncFunctions }))
                .result
        ).toBe('two')
        expect(
            (await execAsync(['_h', op.STRING, '2', op.CALL_GLOBAL, 'stringify', 1, op.RETURN], { asyncFunctions }))
                .result
        ).toBe('zero')
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
            op.CALL_GLOBAL,
            'add',
            2,
            op.INTEGER,
            100,
            op.INTEGER,
            4,
            op.INTEGER,
            3,
            op.CALL_GLOBAL,
            'add',
            2,
            op.PLUS,
            op.PLUS,
            op.CALL_GLOBAL,
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
            op.CALL_GLOBAL,
            'fibonacci',
            1,
            op.INTEGER,
            1,
            op.GET_LOCAL,
            0,
            op.MINUS,
            op.CALL_GLOBAL,
            'fibonacci',
            1,
            op.PLUS,
            op.RETURN,
            op.INTEGER,
            6,
            op.CALL_GLOBAL,
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
            (
                await execAsync(bytecode, {
                    asyncFunctions: {
                        httpGet: async (url: string) => {
                            await delay(1)
                            return 'hello ' + url
                        },
                    },
                })
            ).result
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
                bytecodes: { root: { bytecode } },
                asyncSteps: 1,
                callStack: [
                    {
                        ip: 8,
                        stackStart: 0,
                        argCount: 0,
                        chunk: 'root',
                        closure: {
                            __hogClosure__: true,
                            callable: {
                                __hogCallable__: 'local',
                                name: '',
                                argCount: 0,
                                chunk: 'root',
                                upvalueCount: 0,
                                ip: 1,
                            },
                            upvalues: [],
                        },
                    },
                ],
                throwStack: [],
                declaredFunctions: {},
                maxMemUsed: 16,
                ops: 3,
                stack: [4.2],
                upvalues: [],
                syncDuration: expect.any(Number),
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
            state: {
                asyncSteps: 0,
                bytecodes: { root: { bytecode } },
                callStack: [],
                declaredFunctions: {},
                maxMemUsed: 13,
                ops: 2,
                stack: [],
                upvalues: [],
                throwStack: [],
                syncDuration: expect.any(Number),
            },
        })
    })
    test('no stack pop with repl:true', () => {
        const bytecode = [
            '_h',
            33,
            0.002, // seconds to sleep
            2,
            'toString',
            1,
        ]
        expect(exec(bytecode, { repl: true })).toEqual({
            finished: true,
            result: undefined,
            state: {
                asyncSteps: 0,
                bytecodes: { root: { bytecode } },
                callStack: [],
                declaredFunctions: {},
                maxMemUsed: 13,
                ops: 2,
                stack: ['0.002'],
                upvalues: [],
                throwStack: [],
                syncDuration: expect.any(Number),
            },
        })
    })
    test('exec runs at sync return', () => {
        const bytecode = [
            '_h',
            33,
            0.002, // seconds to sleep
            2,
            'toString',
            1,
            op.RETURN,
        ]
        expect(exec(bytecode)).toEqual({
            finished: true,
            result: '0.002',
            state: {
                asyncSteps: 0,
                bytecodes: {},
                callStack: [],
                declaredFunctions: {},
                maxMemUsed: 13,
                ops: 3,
                stack: [],
                upvalues: [],
                telemetry: undefined,
                throwStack: [],
                syncDuration: expect.any(Number),
            },
        })
    })
    test('bytecode dicts', () => {
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

        // // return {key: 'value'};
        expect(() =>
            execSync(['_h', op.STRING, 'key', op.GET_GLOBAL, 1, op.STRING, 'value', op.DICT, 1, op.RETURN])
        ).toThrow('Global variable not found: key')

        // // return {key: 'value'};
        expect(
            exec(['_h', op.STRING, 'key', op.GET_GLOBAL, 1, op.STRING, 'value', op.DICT, 1, op.RETURN]).error.message
        ).toEqual('Global variable not found: key')

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

    test('bytecode arrays', () => {
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

        // var a := [1, 2, 3]; return a[2];
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
                2,
                op.GET_PROPERTY,
                op.RETURN,
                op.POP,
            ]).result
        ).toEqual(2)

        // return [1, 2, 3][2];
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
                2,
                op.GET_PROPERTY,
                op.RETURN,
            ]).result
        ).toEqual(2)

        // return [1, [2, [3, 4]], 5][2][2][2];
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
                2,
                op.GET_PROPERTY,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.RETURN,
            ]).result
        ).toEqual(4)

        // return [1, [2, [3, 4]], 5][2][2][2] + 1;
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
                2,
                op.GET_PROPERTY,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.PLUS,
                op.RETURN,
            ]).result
        ).toEqual(5)

        // return [1, [2, [3, 4]], 5].2.2.2;
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
                2,
                op.GET_PROPERTY,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.RETURN,
            ]).result
        ).toEqual(4)

        // return [1, 2, 3][0]
        expect(() => execSync(['_h', 33, 1, 33, 2, 33, 3, 43, 3, 33, 0, 45, 38])).toThrow(
            'Hog arrays start from index 1'
        )
    })

    test('bytecode tuples', () => {
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

        // var a := (1, 2, 3); return a[2];
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
                2,
                op.GET_PROPERTY,
                op.RETURN,
                op.POP,
            ]).result
        ).toEqual(2)

        // return (1, (2, (3, 4)), 5)[2][2][2];
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
                2,
                op.GET_PROPERTY,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.RETURN,
            ]).result
        ).toEqual(4)

        // return (1, (2, (3, 4)), 5).2.2.2;
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
                2,
                op.GET_PROPERTY,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.RETURN,
            ]).result
        ).toEqual(4)

        // return (1, (2, (3, 4)), 5)[2][2][2] + 1;
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
                2,
                op.GET_PROPERTY,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.INTEGER,
                2,
                op.GET_PROPERTY,
                op.PLUS,
                op.RETURN,
            ]).result
        ).toEqual(5)
    })

    test('bytecode nested', () => {
        // var r := [1, 2, {'d': (1, 3, 42, 6)}]; return r.3.d.2;
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
                3,
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

        // var r := [1, 2, {'d': (1, 3, 42, 6)}]; return r[3].d[3];
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
                3,
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
        ).toEqual(42)

        // var r := [1, 2, {'d': (1, 3, 42, 6)}]; return r.3['d'][4];
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
                3,
                op.GET_PROPERTY,
                op.STRING,
                'd',
                op.GET_PROPERTY,
                op.INTEGER,
                4,
                op.GET_PROPERTY,
                op.RETURN,
                op.POP,
            ]).result
        ).toEqual(6)

        // var r := {'d': (1, 3, 42, 6)}; return r.d.2;
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
                2,
                op.GET_PROPERTY,
                op.RETURN,
                op.POP,
            ]).result
        ).toEqual(3)
    })

    test('bytecode nested modify', () => {
        // var r := [1, 2, {'d': [1, 3, 42, 3]}];
        // r.3.d.3 := 3;
        // return r.3.d.3;
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
                3,
                op.GET_PROPERTY,
                op.STRING,
                'd',
                op.GET_PROPERTY,
                op.INTEGER,
                3,
                op.INTEGER,
                3,
                op.SET_PROPERTY,
                op.GET_LOCAL,
                0,
                op.INTEGER,
                3,
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
        ).toEqual(3)

        // var r := [1, 2, {'d': [1, 3, 42, 3]}];
        // r[3].d[3] := 3;
        // return r[3].d[3];
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
                3,
                op.GET_PROPERTY,
                op.STRING,
                'd',
                op.GET_PROPERTY,
                op.INTEGER,
                3,
                op.INTEGER,
                3,
                op.SET_PROPERTY,
                op.GET_LOCAL,
                0,
                op.INTEGER,
                3,
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
        ).toEqual(3)

        // var r := [1, 2, {'d': [1, 3, 42, 3]}];
        // r[3].c := [666];
        // return r[3];
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
                3,
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
                3,
                op.GET_PROPERTY,
                op.RETURN,
                op.POP,
            ]).result
        ).toEqual(map({ d: [1, 3, 42, 3], c: [666] }))

        // var r := [1, 2, {'d': [1, 3, 42, 3]}];
        // r[3].d[3] := 3;
        // return r[3].d;
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
                3,
                op.GET_PROPERTY,
                op.STRING,
                'd',
                op.GET_PROPERTY,
                op.INTEGER,
                3,
                op.INTEGER,
                3,
                op.SET_PROPERTY,
                op.GET_LOCAL,
                0,
                op.INTEGER,
                3,
                op.GET_PROPERTY,
                op.STRING,
                'd',
                op.GET_PROPERTY,
                op.RETURN,
                op.POP,
            ]).result
        ).toEqual([1, 3, 3, 3])

        // var r := [1, 2, {'d': [1, 3, 42, 3]}];
        // r.3['d'] := ['a', 'b', 'c', 'd'];
        // return r[3].d[3];
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
                3,
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
                3,
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
        ).toEqual('c')

        // var r := [1, 2, {'d': [1, 3, 42, 3]}];
        // var g := 'd';
        // r.3[g] := ['a', 'b', 'c', 'd'];
        // return r[3].d[3];
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
                3,
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
                3,
                op.GET_PROPERTY,
                op.STRING,
                'd',
                op.GET_PROPERTY,
                op.INTEGER,
                3,
                op.GET_PROPERTY,
                op.RETURN,
                op.POP,
                op.POP,
            ]).result
        ).toEqual('c')
    })

    test('bytecode nested modify dict', () => {
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

    test('bytecode json', () => {
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
        expect(execSync(['_h', op.STRING, '[1,2,3]', op.CALL_GLOBAL, 'jsonParse', 1])).toEqual([1, 2, 3])
        expect(execSync(['_h', ...dict, op.CALL_GLOBAL, 'jsonStringify', 1])).toEqual(
            '{"event":"$pageview","properties":{"$browser":"Chrome","$os":"Windows"}}'
        )
        expect(execSync(['_h', op.INTEGER, 2, ...dict, op.CALL_GLOBAL, 'jsonStringify', 2])).toEqual(
            JSON.stringify({ event: '$pageview', properties: { $browser: 'Chrome', $os: 'Windows' } }, null, 2)
        )
    })

    test('can not modify globals', () => {
        const globals = { globalEvent: { event: '$pageview', properties: { $browser: 'Chrome' } } }
        expect(
            // let event := globalEvent;
            // event.event := '$autocapture';
            // return event;
            exec(['_h', 32, 'globalEvent', 1, 1, 36, 0, 32, 'event', 32, '$autocapture', 46, 36, 0, 38, 35], {
                globals,
            }).result
        ).toEqual(map({ event: '$autocapture', properties: map({ $browser: 'Chrome' }) }))
        expect(globals.globalEvent).toEqual({ event: '$pageview', properties: { $browser: 'Chrome' } })
    })

    test('can modify globals after reading and copying', () => {
        const globals = { globalEvent: { event: '$pageview', properties: { $browser: 'Chrome' } } }
        expect(
            // let event := globalEvent;
            // event.event := '$autocapture';
            // return event;
            exec(['_h', 32, 'globalEvent', 1, 1, 36, 0, 32, 'event', 32, '$autocapture', 46, 36, 0, 38, 35], {
                globals,
            }).result
        ).toEqual(map({ event: '$autocapture', properties: map({ $browser: 'Chrome' }) }))
        expect(globals.globalEvent).toEqual({ event: '$pageview', properties: { $browser: 'Chrome' } })
    })

    test('uses nullish access for globals', () => {
        const globals = { globalVar: { a: { d: 1 } } }
        expect(
            exec(['_H', 1, 32, 'c', 32, 'b', 32, 'a', 32, 'globalVar', 1, 4, 38], {
                globals,
            }).result
        ).toEqual(null)
    })

    test('ternary', () => {
        const values: any[] = []
        const functions = {
            noisy_print: (e) => {
                values.push(e)
                return e
            },
        }
        // return true ? true ? noisy_print('true1') : noisy_print('true') : noisy_print('false')
        const bytecode = [
            '_h',
            op.TRUE,
            op.JUMP_IF_FALSE,
            17,
            op.FALSE,
            op.JUMP_IF_FALSE,
            7,
            op.STRING,
            'true1',
            op.CALL_GLOBAL,
            'noisy_print',
            1,
            op.JUMP,
            5,
            op.STRING,
            'false1',
            op.CALL_GLOBAL,
            'noisy_print',
            1,
            op.JUMP,
            5,
            op.STRING,
            'false2',
            op.CALL_GLOBAL,
            'noisy_print',
            1,
            op.RETURN,
        ]
        expect(execSync(bytecode, { functions })).toEqual('false1')
        expect(values).toEqual(['false1'])
    })

    test('ifNull', () => {
        const values: any[] = []
        const functions = {
            noisy_print: (e) => {
                values.push(e)
                return e
            },
        }
        // return null ?? noisy_print('no'); noisy_print('post')
        const bytecode = [
            '_h',
            op.NULL,
            op.JUMP_IF_STACK_NOT_NULL,
            6,
            op.POP,
            op.STRING,
            'no',
            op.CALL_GLOBAL,
            'noisy_print',
            1,
            op.RETURN,
            op.STRING,
            'post',
            op.CALL_GLOBAL,
            'noisy_print',
            1,
            op.POP,
        ]
        expect(execSync(bytecode, { functions })).toEqual('no')
        expect(values).toEqual(['no'])
    })

    test('uncaught exceptions', () => {
        // throw Error('Not a good day')
        const bytecode1 = ['_h', op.NULL, op.NULL, op.STRING, 'Not a good day', op.CALL_GLOBAL, 'Error', 3, op.THROW]
        expect(() => execSync(bytecode1)).toThrow(new UncaughtHogVMException('Error', 'Not a good day', null))

        // throw RetryError('Not a good day', {'key': 'value'})
        const bytecode2 = [
            '_h',
            op.STRING,
            'key',
            op.STRING,
            'value',
            op.DICT,
            1,
            op.STRING,
            'Not a good day',
            op.CALL_GLOBAL,
            'RetryError',
            2,
            op.THROW,
        ]
        expect(() => execSync(bytecode2)).toThrow(
            new UncaughtHogVMException('RetryError', 'Not a good day', { key: 'value' })
        )
    })

    test('returns serialized state', () => {
        const bytecode = [
            '_h',
            op.STRING,
            'key',
            op.STRING,
            'value',
            op.DICT,
            1,
            op.GET_LOCAL,
            0,
            op.CALL_GLOBAL,
            'fetch',
            1,
        ]
        const result = exec(bytecode, { asyncFunctions: { fetch: async () => null } })
        expect(result).toEqual({
            asyncFunctionArgs: [{ key: 'value' }], // not a Map
            asyncFunctionName: 'fetch',
            finished: false,
            result: undefined,
            state: {
                asyncSteps: 1,
                bytecodes: { root: { bytecode } },
                callStack: [
                    {
                        ip: 12,
                        stackStart: 0,
                        argCount: 0,
                        chunk: 'root',
                        closure: {
                            __hogClosure__: true,
                            callable: {
                                __hogCallable__: 'local',
                                name: '',
                                argCount: 0,
                                chunk: 'root',
                                upvalueCount: 0,
                                ip: 1,
                            },
                            upvalues: [],
                        },
                    },
                ],
                declaredFunctions: {},
                maxMemUsed: 64,
                ops: 5,
                stack: [{ key: 'value' }], // is not a Map
                syncDuration: expect.any(Number),
                throwStack: [],
                upvalues: [],
            },
        })
    })

    test('can serialize/unserialize lambdas', () => {
        // let x := 2
        // let l := (a, b) -> a + b + x
        // sleep(2)
        // x := 10
        // return l(4, 3)
        const bytecode = [
            '_H',
            1,
            33,
            2,
            52,
            'lambda',
            2,
            1,
            9,
            55,
            0,
            36,
            1,
            36,
            0,
            6,
            6,
            38,
            53,
            1,
            true,
            0,
            33,
            2,
            2,
            'sleep',
            1,
            35,
            33,
            10,
            37,
            0,
            33,
            4,
            33,
            3,
            36,
            1,
            54,
            2,
            38,
            35,
            57,
        ]
        const options = {
            asyncFunctions: {
                sleep: async (seconds: number) => new Promise((resolve) => setTimeout(resolve, seconds)),
            },
        }
        const result = exec(bytecode, options)

        expect(result).toEqual({
            result: undefined,
            finished: false,
            asyncFunctionName: 'sleep',
            asyncFunctionArgs: [2],
            state: {
                bytecodes: { root: { bytecode } },
                stack: [
                    2,
                    {
                        __hogClosure__: true,
                        callable: {
                            __hogCallable__: 'local',
                            name: 'lambda',
                            argCount: 2,
                            upvalueCount: 1,
                            ip: 9,
                            chunk: 'root',
                        },
                        upvalues: [1],
                    },
                ],
                upvalues: [
                    {
                        __hogUpValue__: true,
                        location: 0,
                        id: 1,
                        closed: false,
                        value: null,
                    },
                ],
                callStack: [
                    {
                        ip: 27,
                        chunk: 'root',
                        stackStart: 0,
                        argCount: 0,
                        closure: {
                            __hogClosure__: true,
                            callable: {
                                __hogCallable__: 'local',
                                name: '',
                                argCount: 0,
                                upvalueCount: 0,
                                ip: 1,
                                chunk: 'root',
                            },
                            upvalues: [],
                        },
                    },
                ],
                throwStack: [],
                declaredFunctions: {},
                ops: 5,
                asyncSteps: 1,
                syncDuration: expect.any(Number),
                maxMemUsed: 267,
            },
        })
        result.state!.stack.push(null)
        const result2 = exec(result.state!, options)
        expect(result2).toEqual({
            result: 17,
            finished: true,
            state: {
                bytecodes: {},
                stack: expect.any(Array),
                telemetry: undefined,
                upvalues: [],
                callStack: [],
                throwStack: [],
                declaredFunctions: {},
                ops: 19,
                asyncSteps: 1,
                syncDuration: expect.any(Number),
                maxMemUsed: 526,
            },
        })
    })

    test('can serialize/unserialize upvalues', () => {
        // fn outer() {
        //   let x := 'outside'
        //   fn inner() {
        //     print(x)
        //   }
        //
        //   return inner
        // }
        //
        // let closure := outer()
        // sleep(2)
        // return closure()
        const bytecode = [
            '_H',
            1,
            52,
            'outer',
            0,
            0,
            19,
            32,
            'outside',
            52,
            'inner',
            0,
            1,
            3,
            55,
            0,
            38,
            53,
            1,
            true,
            0,
            36,
            1,
            38,
            35,
            57,
            53,
            0,
            36,
            0,
            54,
            0,
            33,
            2,
            2,
            'sleep',
            1,
            35,
            36,
            1,
            54,
            0,
            38,
            35,
            35,
        ]

        const options = {
            asyncFunctions: {
                sleep: async (seconds: number) => new Promise((resolve) => setTimeout(resolve, seconds)),
            },
        }
        const result = exec(bytecode, options)

        expect(result).toEqual({
            finished: false,
            asyncFunctionName: 'sleep',
            asyncFunctionArgs: [2],
            state: {
                bytecodes: { root: { bytecode } },
                stack: [
                    {
                        __hogClosure__: true,
                        callable: {
                            __hogCallable__: 'local',
                            name: 'outer',
                            argCount: 0,
                            upvalueCount: 0,
                            ip: 7,
                            chunk: 'root',
                        },
                        upvalues: [],
                    },
                    {
                        __hogClosure__: true,
                        callable: {
                            __hogCallable__: 'local',
                            name: 'inner',
                            argCount: 0,
                            upvalueCount: 1,
                            ip: 14,
                            chunk: 'root',
                        },
                        upvalues: [1],
                    },
                ],
                upvalues: [
                    {
                        __hogUpValue__: true,
                        id: 1,
                        location: 1,
                        closed: true,
                        value: 'outside',
                    },
                ],
                callStack: [
                    {
                        ip: 37,
                        chunk: 'root',
                        stackStart: 0,
                        argCount: 0,
                        closure: {
                            __hogClosure__: true,
                            callable: {
                                __hogCallable__: 'local',
                                name: '',
                                argCount: 0,
                                upvalueCount: 0,
                                ip: 1,
                                chunk: 'root',
                            },
                            upvalues: [],
                        },
                    },
                ],
                throwStack: [],
                declaredFunctions: {},
                ops: 11,
                asyncSteps: 1,
                syncDuration: expect.any(Number),
                maxMemUsed: 757,
            },
        })
        result.state!.stack.push(null)
        const result2 = exec(result.state!, options)
        expect(result2).toEqual({
            result: 'outside',
            finished: true,
            state: {
                bytecodes: {},
                stack: [],
                upvalues: [],
                callStack: [],
                throwStack: [],
                declaredFunctions: {},
                ops: 17,
                asyncSteps: 1,
                syncDuration: expect.any(Number),
                maxMemUsed: 757,
            },
        })
    })

    test('can serialize/unserialize upvalues v2', () => {
        // fn outer() {
        //   let x := 'outside'
        //   fn inner() {
        //     print(x)
        //     sleep(2)
        //     return x
        //   }
        //   return inner
        // }
        //
        // let closure := outer()
        // return closure()
        const bytecode = [
            '_H',
            1,
            52,
            'outer',
            0,
            0,
            31,
            32,
            'outside',
            52,
            'inner',
            0,
            1,
            15,
            55,
            0,
            2,
            'print',
            1,
            35,
            33,
            2,
            2,
            'sleep',
            1,
            35,
            55,
            0,
            38,
            53,
            1,
            true,
            0,
            36,
            1,
            38,
            35,
            57,
            53,
            0,
            36,
            0,
            54,
            0,
            36,
            1,
            54,
            0,
            38,
            35,
            35,
        ]

        const options = {
            asyncFunctions: {
                sleep: async (seconds: number) => new Promise((resolve) => setTimeout(resolve, seconds)),
            },
        }
        const result = exec(bytecode, options)

        expect(result).toEqual({
            finished: false,
            asyncFunctionName: 'sleep',
            asyncFunctionArgs: [2],
            state: {
                bytecodes: { root: { bytecode } },
                stack: [
                    {
                        __hogClosure__: true,
                        callable: {
                            __hogCallable__: 'local',
                            name: 'outer',
                            argCount: 0,
                            upvalueCount: 0,
                            ip: 7,
                            chunk: 'root',
                        },
                        upvalues: [],
                    },
                    {
                        __hogClosure__: true,
                        callable: {
                            __hogCallable__: 'local',
                            name: 'inner',
                            argCount: 0,
                            upvalueCount: 1,
                            ip: 14,
                            chunk: 'root',
                        },
                        upvalues: [1],
                    },
                ],
                upvalues: [
                    {
                        __hogUpValue__: true,
                        id: 1,
                        location: 1,
                        closed: true,
                        value: 'outside',
                    },
                ],
                callStack: [
                    {
                        ip: 48,
                        chunk: 'root',
                        stackStart: 0,
                        argCount: 0,
                        closure: {
                            __hogClosure__: true,
                            callable: {
                                __hogCallable__: 'local',
                                name: '',
                                argCount: 0,
                                upvalueCount: 0,
                                ip: 1,
                                chunk: 'root',
                            },
                            upvalues: [],
                        },
                    },
                    {
                        ip: 25,
                        chunk: 'root',
                        stackStart: 2,
                        argCount: 0,
                        closure: {
                            __hogClosure__: true,
                            callable: {
                                __hogCallable__: 'local',
                                name: 'inner',
                                argCount: 0,
                                upvalueCount: 1,
                                ip: 14,
                                chunk: 'root',
                            },
                            upvalues: [1],
                        },
                    },
                ],
                throwStack: [],
                declaredFunctions: {},
                ops: 16,
                asyncSteps: 1,
                syncDuration: expect.any(Number),
                maxMemUsed: 757,
            },
        })
        result.state!.stack.push(null)
        const result2 = exec(result.state!, options)
        expect(result2).toEqual({
            result: 'outside',
            finished: true,
            state: {
                bytecodes: {},
                stack: expect.any(Array),
                upvalues: [],
                callStack: [],
                throwStack: [],
                declaredFunctions: {},
                ops: 20,
                asyncSteps: 1,
                syncDuration: expect.any(Number),
                maxMemUsed: 757,
            },
        })
    })

    test('logs telemetry', () => {
        const bytecode = ['_h', op.INTEGER, 1, op.INTEGER, 2, op.PLUS, op.RETURN]
        const result = exec(bytecode, { telemetry: true })
        expect(result).toEqual({
            result: 3,
            finished: true,
            state: {
                bytecodes: {},
                stack: [],
                upvalues: [],
                callStack: [],
                throwStack: [],
                declaredFunctions: {},
                ops: 4,
                asyncSteps: 0,
                syncDuration: expect.any(Number),
                maxMemUsed: 16,
                telemetry: [
                    [expect.any(Number), 'root', 0, 'START', ''],
                    [expect.any(Number), '', 1, '33/INTEGER', '1'],
                    [expect.any(Number), '', 3, '33/INTEGER', '2'],
                    [expect.any(Number), '', 5, '6/PLUS', ''],
                    [expect.any(Number), '', 6, '38/RETURN', ''],
                ],
            },
        })
    })

    test('logs telemetry for calls', () => {
        const bytecode = ['_h', op.FALSE, op.TRUE, op.CALL_GLOBAL, 'concat', 2]
        const result = exec(bytecode, { telemetry: true })
        expect(result).toEqual({
            result: 'truefalse',
            finished: true,
            state: {
                bytecodes: expect.any(Object),
                stack: [],
                upvalues: [],
                callStack: [],
                throwStack: [],
                declaredFunctions: {},
                ops: 3,
                asyncSteps: 0,
                syncDuration: expect.any(Number),
                maxMemUsed: 17,
                telemetry: [
                    [expect.any(Number), 'root', 0, 'START', ''],
                    [expect.any(Number), '', 1, '30/FALSE', ''],
                    [expect.any(Number), '', 2, '29/TRUE', ''],
                    [expect.any(Number), '', 3, '2/CALL_GLOBAL', 'concat'],
                ],
            },
        })
    })

    test('multiple bytecodes', () => {
        const ret = (string: string): BytecodeEntry => ({ bytecode: ['_H', 1, op.STRING, string, op.RETURN] })
        const call = (chunk: string): BytecodeEntry => ({
            bytecode: ['_H', 1, op.STRING, chunk, op.CALL_GLOBAL, 'import', 1, op.RETURN],
        })

        const bytecodes: Record<string, BytecodeEntry> = {
            root: call('code2'),
            code2: ret('banana'),
        }
        const res = exec({ bytecodes })
        expect(res.result).toEqual('banana')
    })

    test('multiple bytecodes via callback', () => {
        const ret = (string: string): BytecodeEntry => ({ bytecode: ['_H', 1, op.STRING, string, op.RETURN] })
        const call = (chunk: string): BytecodeEntry => ({
            // bytecode: ['_H', 1, op.STRING, chunk, op.CALL_GLOBAL, '__importCallable', 1, op.CALL_LOCAL, 0, op.RETURN],
            bytecode: ['_H', 1, op.STRING, chunk, op.CALL_GLOBAL, 'import', 1, op.RETURN],
        })
        const res = exec(call('code2').bytecode, {
            importBytecode: (chunk: string) =>
                ({
                    code2: call('code3'),
                    code3: call('code4'),
                    code4: call('code5'),
                    code5: ret('tomato'),
                })[chunk],
        })
        expect(res.result).toEqual('tomato')
    })

    test('printing sql with sql chunks', () => {
        const bytecode = JSON.parse(
            '["_H", 1, 32, "__hx_ast", 32, "Field", 32, "chain", 32, "event", 43, 1, 42, 2, 32, "__hx_ast", 32, "Field", 32,\n' +
                '"chain", 32, "uuid", 43, 1, 42, 2, 33, 3, 32, "__hx_ast", 32, "SelectQuery", 32, "select", 32, "__hx_ast", 32,\n' +
                '"Field", 32, "chain", 32, "*", 43, 1, 42, 2, 33, 0, 36, 2, 13, 40, 4, 36, 0, 39, 2, 36, 1, 43, 2, 32, "select_from", 32,\n' +
                '"__hx_ast", 32, "JoinExpr", 32, "table", 32, "__hx_ast", 32, "Field", 32, "chain", 32, "events", 43, 1, 42, 2, 42, 2,\n' +
                '42, 3, 2, "toString", 1, 38, 35, 35, 35]'
        )
        const result = exec(bytecode).result
        expect(result).toEqual('sql(SELECT *, event FROM events)')
    })

    test('printing sql with inlined constants', () => {
        const bytecode = JSON.parse(
            '["_H", 1, 32, "$pageview", 32, "__hx_ast", 32, "SelectQuery", 32, "select", 32, "__hx_ast", 32, "Field", 32, "chain",\n' +
                '32, "*", 43, 1, 42, 2, 43, 1, 32, "select_from", 32, "__hx_ast", 32, "JoinExpr", 32, "table", 32, "__hx_ast", 32,\n' +
                '"Field", 32, "chain", 32, "events", 43, 1, 42, 2, 42, 2, 32, "where", 32, "__hx_ast", 32, "CompareOperation", 32,\n' +
                '"left", 32, "__hx_ast", 32, "Field", 32, "chain", 32, "event", 43, 1, 42, 2, 32, "right", 36, 0, 32, "op", 32, "==",\n' +
                '42, 4, 42, 4, 36, 1, 2, "toString", 1, 38, 35, 35]'
        )
        const result = exec(bytecode).result
        expect(result).toEqual("sql(SELECT * FROM events WHERE equals(event, '$pageview'))")
    })

    test('cohort functions', () => {
        // Test inCohort with integer cohort IDs
        // Stack order: push cohort_id first, then list (matching Python)
        let bytecode = [
            '_H',
            1,
            op.INTEGER,
            123, // cohort ID to check
            op.INTEGER,
            45,
            op.INTEGER,
            123,
            op.INTEGER,
            789,
            op.ARRAY,
            3, // person's cohorts: [45, 123, 789]
            op.CALL_GLOBAL,
            'inCohort',
            2,
        ]
        expect(exec(bytecode).result).toBe(true)

        // Test inCohort with cohort ID not in list
        bytecode = [
            '_H',
            1,
            op.INTEGER,
            999, // cohort ID to check (not in list)
            op.INTEGER,
            45,
            op.INTEGER,
            123,
            op.INTEGER,
            789,
            op.ARRAY,
            3, // person's cohorts: [45, 123, 789]
            op.CALL_GLOBAL,
            'inCohort',
            2,
        ]
        expect(exec(bytecode).result).toBe(false)

        // Test notInCohort
        bytecode = [
            '_H',
            1,
            op.INTEGER,
            999, // cohort ID to check (not in list)
            op.INTEGER,
            45,
            op.INTEGER,
            123,
            op.INTEGER,
            789,
            op.ARRAY,
            3, // person's cohorts: [45, 123, 789]
            op.CALL_GLOBAL,
            'notInCohort',
            2,
        ]
        expect(exec(bytecode).result).toBe(true)

        // Test with string cohort IDs
        bytecode = [
            '_H',
            1,
            op.STRING,
            'cohort_abc', // cohort ID to check
            op.STRING,
            'cohort_xyz',
            op.STRING,
            'cohort_abc',
            op.STRING,
            'cohort_def',
            op.ARRAY,
            3, // person's cohorts
            op.CALL_GLOBAL,
            'inCohort',
            2,
        ]
        expect(exec(bytecode).result).toBe(true)

        // Test with mixed types (string ID checking against numeric list)
        bytecode = [
            '_H',
            1,
            op.STRING,
            '123', // string cohort ID
            op.INTEGER,
            45,
            op.INTEGER,
            123,
            op.INTEGER,
            789,
            op.ARRAY,
            3, // person's cohorts: [45, 123, 789]
            op.CALL_GLOBAL,
            'inCohort',
            2,
        ]
        expect(exec(bytecode).result).toBe(true)

        // Test with empty cohort list
        bytecode = [
            '_H',
            1,
            op.INTEGER,
            123, // cohort ID to check
            op.ARRAY,
            0, // empty list
            op.CALL_GLOBAL,
            'inCohort',
            2,
        ]
        expect(exec(bytecode).result).toBe(false)

        // Test with null cohort ID
        bytecode = [
            '_H',
            1,
            op.NULL, // null cohort ID
            op.INTEGER,
            45,
            op.INTEGER,
            123,
            op.ARRAY,
            2,
            op.CALL_GLOBAL,
            'inCohort',
            2,
        ]
        expect(exec(bytecode).result).toBe(false)

        // Test with null list
        bytecode = [
            '_H',
            1,
            op.INTEGER,
            123, // cohort ID
            op.NULL, // null list
            op.CALL_GLOBAL,
            'inCohort',
            2,
        ]
        expect(exec(bytecode).result).toBe(false)

        // Test with globals providing personCohorts
        const options = {
            globals: {
                personCohorts: [45, 123, 789],
            },
        }
        bytecode = [
            '_H',
            1,
            op.INTEGER,
            123, // cohort ID to check
            op.STRING,
            'personCohorts',
            op.GET_GLOBAL,
            1, // Get list from globals
            op.CALL_GLOBAL,
            'inCohort',
            2,
        ]
        expect(exec(bytecode, options).result).toBe(true)
    })
})
