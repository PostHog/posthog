import { ASYNC_STL, STL } from './stl'

const DEFAULT_MAX_ASYNC_STEPS = 100
const DEFAULT_TIMEOUT = 5 // seconds

export const enum Operation {
    FIELD = 1,
    CALL = 2,
    AND = 3,
    OR = 4,
    NOT = 5,
    PLUS = 6,
    MINUS = 7,
    MULTIPLY = 8,
    DIVIDE = 9,
    MOD = 10,
    EQ = 11,
    NOT_EQ = 12,
    GT = 13,
    GT_EQ = 14,
    LT = 15,
    LT_EQ = 16,
    LIKE = 17,
    ILIKE = 18,
    NOT_LIKE = 19,
    NOT_ILIKE = 20,
    IN = 21,
    NOT_IN = 22,
    REGEX = 23,
    NOT_REGEX = 24,
    IREGEX = 25,
    NOT_IREGEX = 26,
    IN_COHORT = 27,
    NOT_IN_COHORT = 28,

    TRUE = 29,
    FALSE = 30,
    NULL = 31,
    STRING = 32,
    INTEGER = 33,
    FLOAT = 34,
    POP = 35,
    GET_LOCAL = 36,
    SET_LOCAL = 37,
    RETURN = 38,
    JUMP = 39,
    JUMP_IF_FALSE = 40,
    DECLARE_FN = 41,
    DICT = 42,
    ARRAY = 43,
    TUPLE = 44,
    GET_PROPERTY = 45,
    SET_PROPERTY_LOCAL = 46,
}

function like(string: string, pattern: string, caseInsensitive = false): boolean {
    pattern = String(pattern)
        .replaceAll(/[-/\\^$*+?.()|[\]{}]/g, '\\$&')
        .replaceAll('%', '.*')
    return new RegExp(pattern, caseInsensitive ? 'i' : undefined).test(string)
}

function getNestedValue(obj: any, chain: any[]): any {
    if (typeof obj === 'object' && obj !== null) {
        for (const key of chain) {
            if (typeof key === 'number') {
                obj = obj[key]
            } else {
                obj = obj[key] ?? null
            }
        }
        return obj
    }
    return null
}
function setNestedValue(obj: any, chain: any[], value: any): void {
    if (typeof obj !== 'object' || obj === null) {
        throw new Error(`Can not set ${chain} on non-object: ${obj}`)
    }
    for (let i = 0; i < chain.length - 1; i++) {
        const key = chain[i]
        obj = obj[key]
    }
    const lastKey = chain[chain.length - 1]
    obj[lastKey] = value
}

interface VMState {
    /** Stack of the VM */
    stack: any[]
    /** Call stack of the VM */
    callStack: [number, number, number][]
    /** Declared functions of the VM */
    declaredFunctions: Record<string, [number, number]>
    /** Instruction pointer of the VM */
    ip: number
    /** How many sync ops have been performed */
    ops: number
    /** How many async steps have been taken */
    asyncSteps: number
    /** Combined duration of sync steps */
    syncDuration: number
}

interface ExecOptions {
    fields?: Record<string, any>
    functions?: Record<string, (...args: any[]) => any>
    asyncFunctions?: Record<string, (...args: any[]) => Promise<any>>
    timeout?: number
    maxAsyncSteps?: number
}

interface ExecResult {
    result: any
    finished: boolean
    asyncFunctionName?: string
    asyncFunctionArgs?: any[]
    state?: VMState
}

export function execSync(bytecode: any[], options?: ExecOptions): any {
    const response = exec(bytecode, options)
    if (response.finished) {
        return response.result
    }
    throw new Error('Unexpected async function call: ' + response.asyncFunctionName)
}

export async function execAsync(bytecode: any[], options?: ExecOptions): Promise<any> {
    let lastState: VMState | undefined = undefined
    while (true) {
        const response = exec(bytecode, options, lastState)
        if (response.finished) {
            return response.result
        }
        if (response.state && response.asyncFunctionName && response.asyncFunctionArgs) {
            lastState = response.state
            if (options?.asyncFunctions && response.asyncFunctionName in options.asyncFunctions) {
                const result = await options?.asyncFunctions[response.asyncFunctionName](...response.asyncFunctionArgs)
                lastState.stack.push(result)
            } else if (response.asyncFunctionName in ASYNC_STL) {
                const result = await ASYNC_STL[response.asyncFunctionName](
                    response.asyncFunctionArgs,
                    response.asyncFunctionName,
                    options?.timeout ?? DEFAULT_TIMEOUT
                )
                lastState.stack.push(result)
            } else {
                throw new Error('Invalid async function call: ' + response.asyncFunctionName)
            }
        } else {
            throw new Error('Invalid async function call')
        }
    }
}

export function exec(bytecode: any[], options?: ExecOptions, vmState?: VMState): ExecResult {
    if (bytecode.length === 0 || bytecode[0] !== '_h') {
        throw new Error("Invalid HogQL bytecode, must start with '_h'")
    }

    const startTime = Date.now()
    let temp: any
    let tempArray: any[]
    let tempObj: Record<string, any> = {}

    const asyncSteps = vmState ? vmState.asyncSteps : 0
    const syncDuration = vmState ? vmState.syncDuration : 0
    const stack: any[] = vmState ? vmState.stack : []
    const callStack: [number, number, number][] = vmState ? vmState.callStack : []
    const declaredFunctions: Record<string, [number, number]> = vmState ? vmState.declaredFunctions : {}
    let ip = vmState ? vmState.ip : 1
    let ops = vmState ? vmState.ops : 0
    const timeout = options?.timeout ?? DEFAULT_TIMEOUT
    const maxAsyncSteps = options?.maxAsyncSteps ?? DEFAULT_MAX_ASYNC_STEPS

    function popStack(): any {
        if (stack.length === 0) {
            throw new Error('Invalid HogQL bytecode, stack is empty')
        }
        return stack.pop()
    }

    function next(): any {
        if (ip >= bytecode.length - 1) {
            throw new Error('Unexpected end of bytecode')
        }
        return bytecode[++ip]
    }
    function checkTimeout(): void {
        if (syncDuration + Date.now() - startTime > timeout * 1000) {
            throw new Error(`Execution timed out after ${timeout} seconds`)
        }
    }

    for (; ip < bytecode.length; ip++) {
        ops += 1
        if ((ops & 127) === 0) {
            checkTimeout()
        }
        switch (bytecode[ip]) {
            case null:
                break
            case Operation.STRING:
                stack.push(next())
                break
            case Operation.FLOAT:
                stack.push(next())
                break
            case Operation.INTEGER:
                stack.push(next())
                break
            case Operation.TRUE:
                stack.push(true)
                break
            case Operation.FALSE:
                stack.push(false)
                break
            case Operation.NULL:
                stack.push(null)
                break
            case Operation.NOT:
                stack.push(!popStack())
                break
            case Operation.AND:
                stack.push(
                    Array(next())
                        .fill(null)
                        .map(() => popStack())
                        .every(Boolean)
                )
                break
            case Operation.OR:
                stack.push(
                    Array(next())
                        .fill(null)
                        .map(() => popStack())
                        .some(Boolean)
                )
                break
            case Operation.PLUS:
                stack.push(Number(popStack()) + Number(popStack()))
                break
            case Operation.MINUS:
                stack.push(Number(popStack()) - Number(popStack()))
                break
            case Operation.DIVIDE:
                stack.push(Number(popStack()) / Number(popStack()))
                break
            case Operation.MULTIPLY:
                stack.push(Number(popStack()) * Number(popStack()))
                break
            case Operation.MOD:
                stack.push(Number(popStack()) % Number(popStack()))
                break
            case Operation.EQ:
                stack.push(popStack() === popStack())
                break
            case Operation.NOT_EQ:
                stack.push(popStack() !== popStack())
                break
            case Operation.GT:
                stack.push(popStack() > popStack())
                break
            case Operation.GT_EQ:
                stack.push(popStack() >= popStack())
                break
            case Operation.LT:
                stack.push(popStack() < popStack())
                break
            case Operation.LT_EQ:
                stack.push(popStack() <= popStack())
                break
            case Operation.LIKE:
                stack.push(like(popStack(), popStack()))
                break
            case Operation.ILIKE:
                stack.push(like(popStack(), popStack(), true))
                break
            case Operation.NOT_LIKE:
                stack.push(!like(popStack(), popStack()))
                break
            case Operation.NOT_ILIKE:
                stack.push(!like(popStack(), popStack(), true))
                break
            case Operation.IN:
                temp = popStack()
                stack.push(popStack().includes(temp))
                break
            case Operation.NOT_IN:
                temp = popStack()
                stack.push(!popStack().includes(temp))
                break
            case Operation.REGEX:
                temp = popStack()
                stack.push(new RegExp(popStack()).test(temp))
                break
            case Operation.NOT_REGEX:
                temp = popStack()
                stack.push(!new RegExp(popStack()).test(temp))
                break
            case Operation.IREGEX:
                temp = popStack()
                stack.push(new RegExp(popStack(), 'i').test(temp))
                break
            case Operation.NOT_IREGEX:
                temp = popStack()
                stack.push(!new RegExp(popStack(), 'i').test(temp))
                break
            case Operation.FIELD: {
                const count = next()
                const chain = []
                for (let i = 0; i < count; i++) {
                    chain.push(popStack())
                }
                stack.push(options?.fields ? getNestedValue(options.fields, chain) : null)
                break
            }
            case Operation.POP:
                popStack()
                break
            case Operation.RETURN:
                if (callStack.length > 0) {
                    const [newIp, stackStart, _] = callStack.pop()!
                    const response = popStack()
                    stack.splice(stackStart)
                    stack.push(response)
                    ip = newIp
                    break
                } else {
                    return {
                        result: popStack(),
                        finished: true,
                    } satisfies ExecResult
                }
            case Operation.GET_LOCAL:
                temp = callStack.length > 0 ? callStack[callStack.length - 1][1] : 0
                stack.push(stack[next() + temp])
                break
            case Operation.SET_LOCAL:
                temp = callStack.length > 0 ? callStack[callStack.length - 1][1] : 0
                stack[next() + temp] = popStack()
                break
            case Operation.GET_PROPERTY:
                temp = next()
                tempArray = []
                for (let i = 0; i < temp; i++) {
                    tempArray.push(popStack())
                }
                stack.push(getNestedValue(popStack(), tempArray))
                break
            case Operation.SET_PROPERTY_LOCAL:
                temp = next()
                tempArray = []
                for (let i = 0; i < temp; i++) {
                    tempArray.push(popStack())
                }
                temp = callStack.length > 0 ? callStack[callStack.length - 1][1] : 0
                setNestedValue(stack[next() + temp], tempArray, popStack())
                break
            case Operation.DICT:
                temp = next() * 2 // number of elements to remove from the stack
                tempArray = stack.splice(stack.length - temp, temp)
                tempObj = {}
                for (let i = 0; i < tempArray.length; i += 2) {
                    tempObj[tempArray[i]] = tempArray[i + 1]
                }
                stack.push(tempObj)
                break
            case Operation.ARRAY:
                temp = next()
                tempArray = stack.splice(stack.length - temp, temp)
                stack.push(tempArray)
                break
            case Operation.TUPLE:
                temp = next()
                tempArray = stack.splice(stack.length - temp, temp)
                stack.push(tempArray)
                break
            case Operation.JUMP:
                temp = next()
                ip += temp
                break
            case Operation.JUMP_IF_FALSE:
                temp = next()
                if (!popStack()) {
                    ip += temp
                }
                break
            case Operation.DECLARE_FN: {
                const name = next()
                const argCount = next()
                const bodyLength = next()
                declaredFunctions[name] = [ip, argCount]
                ip += bodyLength
                break
            }
            case Operation.CALL: {
                checkTimeout()
                const name = next()
                // excluding "toString" only because of JavaScript --> no, it's not declared, it's omnipresent! o_O
                if (name in declaredFunctions && name !== 'toString') {
                    const [funcIp, argLen] = declaredFunctions[name]
                    callStack.push([ip + 1, stack.length - argLen, argLen])
                    ip = funcIp
                } else {
                    const args = Array(next())
                        .fill(null)
                        .map(() => popStack())
                    if (options?.functions && options.functions[name] && name !== 'toString') {
                        stack.push(options.functions[name](...args))
                    } else if (
                        name !== 'toString' &&
                        ((options?.asyncFunctions && options.asyncFunctions[name]) || name in ASYNC_STL)
                    ) {
                        if (asyncSteps >= maxAsyncSteps) {
                            throw new Error(`Exceeded maximum number of async steps: ${maxAsyncSteps}`)
                        }

                        return {
                            result: undefined,
                            finished: false,
                            asyncFunctionName: name,
                            asyncFunctionArgs: args,
                            state: {
                                stack,
                                callStack,
                                declaredFunctions,
                                ip: ip + 1,
                                ops,
                                asyncSteps: asyncSteps + 1,
                                syncDuration: syncDuration + (Date.now() - startTime),
                            },
                        } satisfies ExecResult
                    } else if (name in STL) {
                        stack.push(STL[name](args, name, timeout))
                    } else {
                        throw new Error(`Unsupported function call: ${name}`)
                    }
                }
                break
            }
            default:
                throw new Error(`Unexpected node while running bytecode: ${bytecode[ip]}`)
        }
    }

    if (stack.length > 1) {
        throw new Error('Invalid bytecode. More than one value left on stack')
    } else if (stack.length === 0) {
        return { result: null, finished: true } satisfies ExecResult
    }

    return { result: popStack() ?? null, finished: true } satisfies ExecResult
}
