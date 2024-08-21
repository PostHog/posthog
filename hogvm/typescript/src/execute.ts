import RE2 from 're2'

import { CallFrame, HogCallable, isHogCallable, isHogClosure, isHogError, newHogClosure, ThrowFrame } from './objects'
import { Operation } from './operation'
import { ASYNC_STL, STL } from './stl/stl'
import {
    calculateCost,
    convertHogToJS,
    convertJSToHog,
    getNestedValue,
    HogVMException,
    like,
    setNestedValue,
    UncaughtHogVMException,
} from './utils'

const DEFAULT_MAX_ASYNC_STEPS = 100
const DEFAULT_MAX_MEMORY = 64 * 1024 * 1024 // 64 MB
const DEFAULT_TIMEOUT_MS = 5000 // ms
const MAX_FUNCTION_ARGS_LENGTH = 300

export interface VMState {
    /** Bytecode running in the VM */
    bytecode: any[]
    /** Stack of the VM */
    stack: any[]
    /** Call stack of the VM */
    callStack: CallFrame[] // [number, number, number][]
    /** Throw stack of the VM */
    throwStack: ThrowFrame[]
    /** Declared functions of the VM */
    declaredFunctions: Record<string, [number, number]>
    /** How many sync ops have been performed */
    ops: number
    /** How many async steps have been taken */
    asyncSteps: number
    /** Combined duration of sync steps */
    syncDuration: number
    /** Max memory used */
    maxMemUsed: number
}

export interface ExecOptions {
    /** Global variables to be passed into the function */
    globals?: Record<string, any>
    functions?: Record<string, (...args: any[]) => any>
    asyncFunctions?: Record<string, (...args: any[]) => Promise<any>>
    /** Timeout in milliseconds */
    timeout?: number
    /** Max number of async function that can happen. When reached the function will throw */
    maxAsyncSteps?: number
    /** Memory limit in bytes. This is calculated based on the size of the VM stack. */
    memoryLimit?: number
}

export interface ExecResult {
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
    throw new HogVMException('Unexpected async function call: ' + response.asyncFunctionName)
}

export async function execAsync(bytecode: any[], options?: ExecOptions): Promise<any> {
    let vmState: VMState | undefined = undefined
    while (true) {
        const response = exec(vmState ?? bytecode, options)
        if (response.finished) {
            return response.result
        }
        if (response.state && response.asyncFunctionName && response.asyncFunctionArgs) {
            vmState = response.state
            if (options?.asyncFunctions && response.asyncFunctionName in options.asyncFunctions) {
                const result = await options?.asyncFunctions[response.asyncFunctionName](
                    ...response.asyncFunctionArgs.map(convertHogToJS)
                )
                vmState.stack.push(convertJSToHog(result))
            } else if (response.asyncFunctionName in ASYNC_STL) {
                const result = await ASYNC_STL[response.asyncFunctionName](
                    response.asyncFunctionArgs,
                    response.asyncFunctionName,
                    options?.timeout ?? DEFAULT_TIMEOUT_MS
                )
                vmState.stack.push(result)
            } else {
                throw new HogVMException('Invalid async function call: ' + response.asyncFunctionName)
            }
        } else {
            throw new HogVMException('Invalid async function call')
        }
    }
}

export function exec(code: any[] | VMState, options?: ExecOptions): ExecResult {
    let vmState: VMState | undefined = undefined
    let bytecode: any[] | undefined = undefined
    if (!Array.isArray(code)) {
        vmState = code
        bytecode = vmState.bytecode
    } else {
        bytecode = code
    }

    if (!bytecode || bytecode.length === 0 || bytecode[0] !== '_h') {
        throw new HogVMException("Invalid HogQL bytecode, must start with '_h'")
    }

    const startTime = Date.now()
    let temp: any
    let temp2: any
    let tempArray: any[]
    let tempMap: Map<string, any> = new Map()

    const asyncSteps = vmState ? vmState.asyncSteps : 0
    const syncDuration = vmState ? vmState.syncDuration : 0
    const stack: any[] = vmState ? vmState.stack : []
    const memStack: number[] = stack.map((s) => calculateCost(s))
    const callStack: CallFrame[] = vmState ? vmState.callStack : []
    const throwStack: ThrowFrame[] = vmState ? vmState.throwStack : []
    const declaredFunctions: Record<string, [number, number]> = vmState ? vmState.declaredFunctions : {}
    let memUsed = memStack.reduce((acc, val) => acc + val, 0)
    let maxMemUsed = Math.max(vmState ? vmState.maxMemUsed : 0, memUsed)
    const memLimit = options?.memoryLimit ?? DEFAULT_MAX_MEMORY
    let ops = vmState ? vmState.ops : 0
    const timeout = options?.timeout ?? DEFAULT_TIMEOUT_MS
    const maxAsyncSteps = options?.maxAsyncSteps ?? DEFAULT_MAX_ASYNC_STEPS

    if (callStack.length === 0) {
        callStack.push({
            ip: 1,
            stackStart: 0,
            argCount: 0,
            closure: newHogClosure({
                __hogCallable__: 'main',
                name: '',
                argCount: 0,
                upvalueCount: 0,
                ip: 1,
            }),
        } satisfies CallFrame)
    }

    let frame: CallFrame = callStack[callStack.length - 1]

    function popStack(): any {
        if (stack.length === 0) {
            throw new HogVMException('Invalid HogQL bytecode, stack is empty')
        }
        memUsed -= memStack.pop() ?? 0
        return stack.pop()
    }

    function pushStack(value: any): any {
        memStack.push(calculateCost(value))
        memUsed += memStack[memStack.length - 1]
        maxMemUsed = Math.max(maxMemUsed, memUsed)
        if (memUsed > memLimit && memLimit > 0) {
            throw new HogVMException(`Memory limit of ${memLimit} bytes exceeded. Tried to allocate ${memUsed} bytes.`)
        }
        return stack.push(value)
    }

    function spliceStack2(start: number, deleteCount?: number): any[] {
        memUsed -= memStack.splice(start, deleteCount).reduce((acc, val) => acc + val, 0)
        return stack.splice(start, deleteCount)
    }
    function spliceStack1(start: number): any[] {
        memUsed -= memStack.splice(start).reduce((acc, val) => acc + val, 0)
        return stack.splice(start)
    }

    function next(): any {
        if (frame.ip >= bytecode!.length - 1) {
            throw new HogVMException('Unexpected end of bytecode')
        }
        return bytecode![++frame.ip]
    }

    function checkTimeout(): void {
        if (syncDuration + Date.now() - startTime > timeout) {
            throw new HogVMException(`Execution timed out after ${timeout / 1000} seconds. Performed ${ops} ops.`)
        }
    }
    function getFinishedState(): VMState {
        return {
            bytecode: [],
            stack: [],
            callStack: [],
            throwStack: [],
            declaredFunctions: {},
            ops,
            asyncSteps,
            syncDuration: syncDuration + (Date.now() - startTime),
            maxMemUsed,
        }
    }

    while (frame.ip < bytecode.length) {
        ops += 1
        if ((ops & 127) === 0) {
            checkTimeout()
        }
        switch (bytecode[frame.ip]) {
            case null:
                break
            case Operation.STRING:
                pushStack(next())
                break
            case Operation.FLOAT:
                pushStack(next())
                break
            case Operation.INTEGER:
                pushStack(next())
                break
            case Operation.TRUE:
                pushStack(true)
                break
            case Operation.FALSE:
                pushStack(false)
                break
            case Operation.NULL:
                pushStack(null)
                break
            case Operation.NOT:
                pushStack(!popStack())
                break
            case Operation.AND:
                temp = next()
                temp2 = true
                for (let i = 0; i < temp; i++) {
                    temp2 = !!popStack() && temp2
                }
                pushStack(temp2)
                break
            case Operation.OR:
                temp = next()
                temp2 = false
                for (let i = 0; i < temp; i++) {
                    temp2 = !!popStack() || temp2
                }
                pushStack(temp2)
                break
            case Operation.PLUS:
                pushStack(Number(popStack()) + Number(popStack()))
                break
            case Operation.MINUS:
                pushStack(Number(popStack()) - Number(popStack()))
                break
            case Operation.DIVIDE:
                pushStack(Number(popStack()) / Number(popStack()))
                break
            case Operation.MULTIPLY:
                pushStack(Number(popStack()) * Number(popStack()))
                break
            case Operation.MOD:
                pushStack(Number(popStack()) % Number(popStack()))
                break
            case Operation.EQ:
                pushStack(popStack() === popStack())
                break
            case Operation.NOT_EQ:
                pushStack(popStack() !== popStack())
                break
            case Operation.GT:
                pushStack(popStack() > popStack())
                break
            case Operation.GT_EQ:
                pushStack(popStack() >= popStack())
                break
            case Operation.LT:
                pushStack(popStack() < popStack())
                break
            case Operation.LT_EQ:
                pushStack(popStack() <= popStack())
                break
            case Operation.LIKE:
                pushStack(like(popStack(), popStack()))
                break
            case Operation.ILIKE:
                pushStack(like(popStack(), popStack(), true))
                break
            case Operation.NOT_LIKE:
                pushStack(!like(popStack(), popStack()))
                break
            case Operation.NOT_ILIKE:
                pushStack(!like(popStack(), popStack(), true))
                break
            case Operation.IN:
                temp = popStack()
                pushStack(popStack().includes(temp))
                break
            case Operation.NOT_IN:
                temp = popStack()
                pushStack(!popStack().includes(temp))
                break
            case Operation.REGEX:
                temp = popStack()
                pushStack(new RE2(popStack()).test(temp))
                break
            case Operation.NOT_REGEX:
                temp = popStack()
                pushStack(!new RE2(popStack()).test(temp))
                break
            case Operation.IREGEX:
                temp = popStack()
                pushStack(new RE2(popStack(), 'i').test(temp))
                break
            case Operation.NOT_IREGEX:
                temp = popStack()
                pushStack(!new RE2(popStack(), 'i').test(temp))
                break
            case Operation.GET_GLOBAL: {
                const count = next()
                const chain = []
                for (let i = 0; i < count; i++) {
                    chain.push(popStack())
                }

                if (options?.globals && chain[0] in options.globals && Object.hasOwn(options.globals, chain[0])) {
                    pushStack(convertJSToHog(getNestedValue(options.globals, chain)))
                } else if (
                    options?.asyncFunctions &&
                    chain.length == 1 &&
                    Object.hasOwn(options.asyncFunctions, chain[0]) &&
                    options.asyncFunctions[chain[0]]
                ) {
                    pushStack(
                        newHogClosure({
                            __hogCallable__: 'async',
                            name: chain[0],
                            argCount: 0, // TODO
                            ip: -1,
                        } satisfies HogCallable)
                    )
                } else if (chain.length == 1 && chain[0] in ASYNC_STL && Object.hasOwn(ASYNC_STL, chain[0])) {
                    pushStack(
                        newHogClosure({
                            __hogCallable__: 'async',
                            argCount: 0, // TODO
                            ip: -1,
                        } satisfies HogCallable)
                    )
                } else if (chain.length == 1 && chain[0] in STL && Object.hasOwn(STL, chain[0])) {
                    pushStack(
                        newHogClosure({
                            __hogCallable__: 'stl',
                            argCount: 0, // TODO
                            ip: -1,
                            name: chain[0],
                        } satisfies HogCallable)
                    )
                } else {
                    throw new HogVMException(`Global variable not found: ${chain.join('.')}`)
                }
                break
            }
            case Operation.POP:
                popStack()
                break
            case Operation.RETURN:
                if (callStack.length > 1) {
                    const stackStart = callStack.pop()!.stackStart
                    const response = popStack()
                    spliceStack1(stackStart)
                    pushStack(response)
                    frame = callStack[callStack.length - 1]
                    continue // resume the loop without incrementing frame.ip
                } else {
                    return {
                        result: popStack(),
                        finished: true,
                        state: getFinishedState(),
                    } satisfies ExecResult
                }
            case Operation.GET_LOCAL:
                temp = callStack.length > 0 ? callStack[callStack.length - 1].stackStart : 0
                pushStack(stack[next() + temp])
                break
            case Operation.SET_LOCAL:
                temp = (callStack.length > 0 ? callStack[callStack.length - 1].stackStart : 0) + next()
                stack[temp] = popStack()
                temp2 = memStack[temp]
                memStack[temp] = calculateCost(stack[temp])
                memUsed += memStack[temp] - temp2
                maxMemUsed = Math.max(maxMemUsed, memUsed)
                break
            case Operation.GET_PROPERTY:
                temp = popStack() // property
                pushStack(getNestedValue(popStack(), [temp]))
                break
            case Operation.GET_PROPERTY_NULLISH:
                temp = popStack() // property
                pushStack(getNestedValue(popStack(), [temp], true))
                break
            case Operation.SET_PROPERTY:
                temp = popStack() // value
                temp2 = popStack() // field
                setNestedValue(popStack(), [temp2], temp)
                break
            case Operation.DICT:
                temp = next() * 2 // number of elements to remove from the stack
                tempArray = spliceStack2(stack.length - temp, temp)
                tempMap = new Map()
                for (let i = 0; i < tempArray.length; i += 2) {
                    tempMap.set(tempArray[i], tempArray[i + 1])
                }
                pushStack(tempMap)
                break
            case Operation.ARRAY:
                temp = next()
                tempArray = spliceStack2(stack.length - temp, temp)
                pushStack(tempArray)
                break
            case Operation.TUPLE:
                temp = next()
                tempArray = spliceStack2(stack.length - temp, temp)
                ;(tempArray as any).__isHogTuple = true
                pushStack(tempArray)
                break
            case Operation.JUMP:
                temp = next()
                frame.ip += temp
                break
            case Operation.JUMP_IF_FALSE:
                temp = next()
                if (!popStack()) {
                    frame.ip += temp
                }
                break
            case Operation.JUMP_IF_STACK_NOT_NULL:
                temp = next()
                if (stack.length > 0 && stack[stack.length - 1] !== null) {
                    frame.ip += temp
                }
                break
            case Operation.DECLARE_FN: {
                // DEPRECATED
                const name = next()
                const argCount = next()
                const bodyLength = next()
                declaredFunctions[name] = [frame.ip + 1, argCount]
                frame.ip += bodyLength
                break
            }
            case Operation.CALLABLE: {
                const name = next() // TODO: do we need it? it could change as the variable is reassigned
                const argCount = next()
                const bodyLength = next()
                const callable = {
                    __hogCallable__: 'local',
                    argCount,
                    // upvalueCount,
                    ip: frame.ip + 1,
                    name,
                } satisfies HogCallable
                pushStack(callable)
                frame.ip += bodyLength
                break
            }
            case Operation.CLOSURE: {
                pushStack(newHogClosure(popStack(), []))
                break
            }
            case Operation.CALL_GLOBAL: {
                checkTimeout()
                const name = next()
                if (name in declaredFunctions && name !== 'toString') {
                    // This is for backwards compatibility. We use a closure on the stack with local functions now.
                    const [funcIp, argLen] = declaredFunctions[name]
                    frame.ip += 1 // advance for when we return
                    frame = {
                        ip: funcIp,
                        stackStart: stack.length - argLen,
                        argCount: argLen,
                        closure: newHogClosure({
                            __hogCallable__: 'stl',
                            argCount: argLen,
                            upvalueCount: 0,
                            ip: -1,
                            name: name,
                        } satisfies HogCallable),
                    } satisfies CallFrame
                    callStack.push(frame)
                    continue // resume the loop without incrementing frame.ip
                } else {
                    // Shortcut for calling STL functions (can also be done with an STL function closure)
                    temp = next() // args.length
                    if (temp > stack.length) {
                        throw new HogVMException('Not enough arguments on the stack')
                    }
                    if (temp > MAX_FUNCTION_ARGS_LENGTH) {
                        throw new HogVMException('Too many arguments')
                    }
                    const args = Array(temp)
                        .fill(null)
                        .map(() => popStack())

                    if (options?.functions && Object.hasOwn(options.functions, name) && options.functions[name]) {
                        pushStack(convertJSToHog(options.functions[name](...args.map(convertHogToJS))))
                    } else if (
                        name !== 'toString' &&
                        ((options?.asyncFunctions &&
                            Object.hasOwn(options.asyncFunctions, name) &&
                            options.asyncFunctions[name]) ||
                            name in ASYNC_STL)
                    ) {
                        if (asyncSteps >= maxAsyncSteps) {
                            throw new HogVMException(`Exceeded maximum number of async steps: ${maxAsyncSteps}`)
                        }

                        frame.ip += 1 // so we resume at the next address

                        return {
                            result: undefined,
                            finished: false,
                            asyncFunctionName: name,
                            asyncFunctionArgs: args,
                            state: {
                                bytecode,
                                stack,
                                callStack,
                                throwStack,
                                declaredFunctions,
                                ops,
                                asyncSteps: asyncSteps + 1,
                                syncDuration: syncDuration + (Date.now() - startTime),
                                maxMemUsed,
                            },
                        } satisfies ExecResult
                    } else if (name in STL) {
                        pushStack(STL[name].fn(args, name, timeout))
                    } else {
                        throw new HogVMException(`Unsupported function call: ${name}`)
                    }
                }
                break
            }
            case Operation.CALL_LOCAL: {
                checkTimeout()
                const closure = popStack()
                if (!isHogClosure(closure)) {
                    throw new HogVMException(`Invalid closure: ${JSON.stringify(closure)}`)
                }
                if (!isHogCallable(closure.callable)) {
                    throw new HogVMException(`Invalid callable: ${JSON.stringify(closure.callable)}`)
                }
                temp = next() // args.length
                if (temp > stack.length) {
                    throw new HogVMException('Not enough arguments on the stack')
                }
                if (temp > MAX_FUNCTION_ARGS_LENGTH) {
                    throw new HogVMException('Too many arguments')
                }
                if (closure.callable.__hogCallable__ === 'local') {
                    if (closure.callable.argCount > temp) {
                        for (let i = temp; i < closure.callable.argCount; i++) {
                            pushStack(null)
                        }
                    } else if (closure.callable.argCount < temp) {
                        throw new HogVMException(
                            `Too many arguments. Passed ${temp}, expected ${closure.callable.argCount}`
                        )
                    }
                    frame.ip += 1 // advance for when we return
                    frame = {
                        ip: closure.callable.ip,
                        stackStart: stack.length - closure.callable.argCount,
                        argCount: closure.callable.argCount,
                        closure,
                    } satisfies CallFrame
                    callStack.push(frame)
                    continue // resume the loop without incrementing frame.ip
                } else if (closure.callable.__hogCallable__ === 'stl') {
                    if (!closure.callable.name || !(closure.callable.name in STL)) {
                        throw new HogVMException(`Unsupported function call: ${closure.callable.name}`)
                    }
                    const stlFn = STL[closure.callable.name]
                    if (stlFn.minArgs !== undefined && temp < stlFn.minArgs) {
                        throw new HogVMException(
                            `Function ${closure.callable.name} requires at least ${stlFn.minArgs} arguments`
                        )
                    }
                    if (stlFn.maxArgs !== undefined && temp > stlFn.maxArgs) {
                        throw new HogVMException(
                            `Function ${closure.callable.name} requires at most ${stlFn.maxArgs} arguments`
                        )
                    }
                    const args = Array(temp)
                        .fill(null)
                        .map(() => popStack())
                    if (stlFn.maxArgs !== undefined && args.length < stlFn.maxArgs) {
                        for (let i = args.length; i < stlFn.maxArgs; i++) {
                            args.push(null)
                        }
                    }
                    pushStack(stlFn.fn(args, closure.callable.name, timeout))
                } else if (closure.callable.__hogCallable__ === 'async') {
                    if (asyncSteps >= maxAsyncSteps) {
                        throw new HogVMException(`Exceeded maximum number of async steps: ${maxAsyncSteps}`)
                    }
                    const args = Array(temp)
                        .fill(null)
                        .map(() => popStack())
                    return {
                        result: undefined,
                        finished: false,
                        asyncFunctionName: closure.callable.name,
                        asyncFunctionArgs: args,
                        state: {
                            bytecode,
                            stack,
                            callStack,
                            throwStack,
                            declaredFunctions,
                            ops,
                            asyncSteps: asyncSteps + 1,
                            syncDuration: syncDuration + (Date.now() - startTime),
                            maxMemUsed,
                        },
                    } satisfies ExecResult
                } else {
                    throw new HogVMException(`Unsupported function call: ${closure.callable.name}`)
                }
                break
            }
            case Operation.TRY:
                throwStack.push({
                    callStackLen: callStack.length,
                    stackLen: stack.length,
                    catchIp: frame.ip + 1 + next(),
                })
                break
            case Operation.POP_TRY:
                if (throwStack.length > 0) {
                    throwStack.pop()
                } else {
                    throw new HogVMException('Invalid operation POP_TRY: no try block to pop')
                }
                break
            case Operation.THROW: {
                const exception = popStack()
                if (!isHogError(exception)) {
                    throw new HogVMException('Can not throw: value is not of type Error')
                }
                if (throwStack.length > 0) {
                    const { callStackLen, stackLen, catchIp } = throwStack.pop()!
                    spliceStack1(stackLen)
                    memUsed -= memStack.splice(stackLen).reduce((acc, val) => acc + val, 0)
                    callStack.splice(callStackLen)
                    pushStack(exception)
                    frame = callStack[callStack.length - 1]
                    frame.ip = catchIp
                    continue // resume the loop without incrementing frame.ip
                } else {
                    throw new UncaughtHogVMException(exception.type, exception.message, exception.payload)
                }
            }
            default:
                throw new HogVMException(`Unexpected node while running bytecode: ${bytecode[frame.ip]}`)
        }

        // use "continue" to skip incrementing frame.ip each iteration
        frame.ip++
    }

    if (stack.length > 1) {
        throw new HogVMException('Invalid bytecode. More than one value left on stack')
    }

    if (stack.length === 0) {
        return { result: null, finished: true, state: getFinishedState() } satisfies ExecResult
    }

    return { result: popStack() ?? null, finished: true, state: getFinishedState() } satisfies ExecResult
}
