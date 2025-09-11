import {
    CALLSTACK_LENGTH,
    DEFAULT_MAX_ASYNC_STEPS,
    DEFAULT_MAX_MEMORY,
    DEFAULT_TIMEOUT_MS,
    MAX_FUNCTION_ARGS_LENGTH,
} from './constants'
import { isHogCallable, isHogClosure, isHogError, isHogUpValue, newHogCallable, newHogClosure } from './objects'
import { Operation, operations } from './operation'
import { BYTECODE_STL } from './stl/bytecode'
import { ASYNC_STL, STL } from './stl/stl'
import {
    BytecodeEntry,
    Bytecodes,
    CallFrame,
    ExecOptions,
    ExecResult,
    HogUpValue,
    Telemetry,
    ThrowFrame,
    VMState,
} from './types'
import {
    calculateCost,
    convertHogToJS,
    convertJSToHog,
    getNestedValue,
    HogVMException,
    like,
    setNestedValue,
    UncaughtHogVMException,
    unifyComparisonTypes,
} from './utils'

export function execSync(bytecode: any[] | VMState | Bytecodes, options?: ExecOptions): any {
    const response = exec(bytecode, options)
    if (response.finished) {
        return response.result
    }
    if (response.error) {
        throw response.error
    }
    throw new HogVMException('Unexpected async function call: ' + response.asyncFunctionName)
}

export async function execAsync(bytecode: any[] | VMState | Bytecodes, options?: ExecOptions): Promise<ExecResult> {
    let vmState: VMState | undefined = undefined
    while (true) {
        const response = exec(vmState ?? bytecode, options)
        if (response.finished) {
            return response
        }
        if (response.error) {
            throw response.error
        }
        if (response.state && response.asyncFunctionName && response.asyncFunctionArgs) {
            vmState = response.state
            if (options?.asyncFunctions && response.asyncFunctionName in options.asyncFunctions) {
                const result = await options?.asyncFunctions[response.asyncFunctionName](...response.asyncFunctionArgs)
                vmState.stack.push(result)
            } else if (response.asyncFunctionName in ASYNC_STL) {
                const result = await ASYNC_STL[response.asyncFunctionName].fn(
                    response.asyncFunctionArgs,
                    response.asyncFunctionName,
                    options
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

export function exec(input: any[] | VMState | Bytecodes, options?: ExecOptions): ExecResult {
    const startTime = Date.now()
    let vmState: VMState | undefined = undefined

    let bytecodes: Record<string, BytecodeEntry>
    if (!Array.isArray(input)) {
        if ('stack' in input) {
            vmState = input
        }
        bytecodes = (input as VMState).bytecode
            ? { root: { bytecode: (input as VMState).bytecode as any[] } }
            : input.bytecodes
    } else {
        bytecodes = { root: { bytecode: input } }
    }
    const rootBytecode = bytecodes.root.bytecode
    if (!rootBytecode || rootBytecode.length === 0 || (rootBytecode[0] !== '_h' && rootBytecode[0] !== '_H')) {
        throw new HogVMException("Invalid HogQL bytecode, must start with '_H'")
    }
    const version = rootBytecode[0] === '_H' ? (rootBytecode[1] ?? 0) : 0

    let temp: any
    let temp2: any
    let tempArray: any[]
    let tempMap: Map<string, any> = new Map()

    const asyncSteps = vmState ? vmState.asyncSteps : 0
    const syncDuration = vmState ? vmState.syncDuration : 0
    const sortedUpValues: HogUpValue[] = vmState
        ? vmState.upvalues.map((v) => ({ ...v, value: convertJSToHog(v.value) }))
        : []
    const upvaluesById: Record<number, HogUpValue> = {}
    for (const upvalue of sortedUpValues) {
        upvaluesById[upvalue.id] = upvalue
    }
    const stack: any[] = vmState ? vmState.stack.map((v) => convertJSToHog(v)) : []
    const memStack: number[] = stack.map((s) => calculateCost(s))
    const callStack: CallFrame[] = vmState
        ? vmState.callStack.map((v) => ({ ...v, closure: convertJSToHog(v.closure) }))
        : []
    const throwStack: ThrowFrame[] = vmState ? vmState.throwStack : []
    const declaredFunctions: Record<string, [number, number]> = vmState ? vmState.declaredFunctions : {}
    let memUsed = memStack.reduce((acc, val) => acc + val, 0)
    let maxMemUsed = Math.max(vmState ? vmState.maxMemUsed : 0, memUsed)
    const memLimit = options?.memoryLimit ?? DEFAULT_MAX_MEMORY
    let ops = vmState ? vmState.ops : 0
    const timeout = options?.timeout ?? DEFAULT_TIMEOUT_MS
    const maxAsyncSteps = options?.maxAsyncSteps ?? DEFAULT_MAX_ASYNC_STEPS
    const rootGlobals: Record<string, any> =
        bytecodes.root?.globals && options?.globals
            ? { ...bytecodes.root.globals, ...options.globals }
            : (bytecodes.root?.globals ?? options?.globals ?? {})

    if (callStack.length === 0) {
        callStack.push({
            ip: 0,
            chunk: 'root',
            stackStart: 0,
            argCount: 0,
            closure: newHogClosure(
                newHogCallable('local', {
                    name: '',
                    argCount: 0,
                    upvalueCount: 0,
                    ip: 1,
                    chunk: 'root',
                })
            ),
        } satisfies CallFrame)
    }
    let frame: CallFrame = callStack[callStack.length - 1]
    let chunkBytecode: any[] = rootBytecode
    let chunkGlobals = rootGlobals
    let lastChunk = frame.chunk
    let lastTime = startTime

    const telemetry: Telemetry[] = [[startTime, lastChunk, 0, 'START', '']]

    const setChunkBytecode = (): void => {
        if (!frame.chunk || frame.chunk === 'root') {
            chunkBytecode = rootBytecode
            chunkGlobals = rootGlobals
        } else if (frame.chunk.startsWith('stl/') && frame.chunk.substring(4) in BYTECODE_STL) {
            chunkBytecode = BYTECODE_STL[frame.chunk.substring(4)][1]
            chunkGlobals = {}
        } else if (bytecodes[frame.chunk]) {
            chunkBytecode = bytecodes[frame.chunk].bytecode
            chunkGlobals = bytecodes[frame.chunk].globals ?? {}
        } else if (options?.importBytecode) {
            const chunk = options.importBytecode(frame.chunk)
            if (chunk) {
                bytecodes[frame.chunk] = chunk // cache for later
                chunkBytecode = chunk.bytecode
                chunkGlobals = chunk.globals ?? {}
            } else {
                throw new HogVMException(`Unknown chunk: ${frame.chunk}`)
            }
        } else {
            throw new HogVMException(`Unknown chunk: ${frame.chunk}`)
        }
        if (frame.ip === 0 && (chunkBytecode[0] === '_H' || chunkBytecode[0] === '_h')) {
            // TODO: store chunkVersion
            frame.ip += chunkBytecode[0] === '_H' ? 2 : 1
        }
    }
    setChunkBytecode()

    function popStack(): any {
        if (stack.length === 0) {
            logTelemetry()
            throw new HogVMException('Invalid HogQL bytecode, stack is empty, can not pop')
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

    function stackKeepFirstElements(count: number): any[] {
        if (count < 0 || stack.length < count) {
            throw new HogVMException('Stack underflow')
        }
        for (let i = sortedUpValues.length - 1; i >= 0; i--) {
            if (sortedUpValues[i].location >= count) {
                if (!sortedUpValues[i].closed) {
                    sortedUpValues[i].closed = true
                    sortedUpValues[i].value = stack[sortedUpValues[i].location]
                }
            } else {
                // upvalues are sorted by location, so we can break early
                break
            }
        }
        memUsed -= memStack.splice(count).reduce((acc, val) => acc + val, 0)
        return stack.splice(count)
    }

    function next(): any {
        if (frame.ip >= chunkBytecode.length - 1) {
            throw new HogVMException('Unexpected end of bytecode')
        }
        return chunkBytecode[++frame.ip]
    }

    function checkTimeout(): void {
        if (syncDuration + Date.now() - startTime > timeout) {
            throw new HogVMException(`Execution timed out after ${timeout / 1000} seconds. Performed ${ops} ops.`)
        }
    }

    function getVMState(): VMState {
        return {
            bytecodes: bytecodes,
            stack: stack.map((v) => convertHogToJS(v)),
            upvalues: sortedUpValues.map((v) => ({ ...v, value: convertHogToJS(v.value) })),
            callStack: callStack.map((v) => ({
                ...v,
                closure: convertHogToJS(v.closure),
            })),
            throwStack,
            declaredFunctions,
            ops,
            asyncSteps,
            syncDuration: syncDuration + (Date.now() - startTime),
            maxMemUsed,
            telemetry: options?.telemetry ? telemetry : undefined,
        }
    }

    function captureUpValue(index: number): HogUpValue {
        for (let i = sortedUpValues.length - 1; i >= 0; i--) {
            if (sortedUpValues[i].location < index) {
                break
            }
            if (sortedUpValues[i].location === index) {
                return sortedUpValues[i]
            }
        }
        const createdUpValue = {
            __hogUpValue__: true,
            id: sortedUpValues.length + 1, // used to deduplicate post deserialization
            location: index,
            closed: false,
            value: null,
        } satisfies HogUpValue
        upvaluesById[createdUpValue.id] = createdUpValue
        sortedUpValues.push(createdUpValue)
        sortedUpValues.sort((a, b) => a.location - b.location)
        return createdUpValue
    }

    function regexMatch(): (regex: string, value: string) => boolean {
        if (!options?.external?.regex?.match) {
            throw new HogVMException('Set options.external.regex.match for RegEx support')
        }
        return (regex: string, value: string): boolean =>
            regex && value ? !!options.external?.regex?.match(regex, value) : false
    }

    const logTelemetry = (): void => {
        const op = chunkBytecode[frame.ip]
        const newTime = new Date().getTime()
        let debug = ''
        if (op === Operation.CALL_LOCAL || op === Operation.GET_PROPERTY || op === Operation.GET_PROPERTY_NULLISH) {
            debug = String(stack[stack.length - 1])
        } else if (
            op === Operation.GET_GLOBAL ||
            op === Operation.CALL_GLOBAL ||
            op === Operation.STRING ||
            op === Operation.INTEGER ||
            op === Operation.FLOAT
        ) {
            debug = String(chunkBytecode[frame.ip + 1])
        }
        telemetry.push([
            newTime !== lastTime ? newTime - lastTime : 0,
            frame.chunk !== lastChunk ? frame.chunk : '',
            frame.ip,
            typeof chunkBytecode[frame.ip] === 'number'
                ? String(chunkBytecode[frame.ip]) +
                  (operations[chunkBytecode[frame.ip]] ? `/${operations[chunkBytecode[frame.ip]]}` : '')
                : '???',
            debug,
        ])
        lastChunk = frame.chunk
        lastTime = newTime
    }

    const nextOp = options?.telemetry
        ? () => {
              ops += 1
              logTelemetry()
              if ((ops & 31) === 0) {
                  checkTimeout()
              }
          }
        : () => {
              ops += 1
              if ((ops & 31) === 0) {
                  checkTimeout()
              }
          }

    try {
        while (true) {
            // Return or jump back to the previous call frame if ran out of bytecode to execute in this one
            if (frame.ip >= chunkBytecode.length) {
                const lastCallFrame = callStack.pop()
                // Also ran out of call frames. We're done.
                if (!lastCallFrame || callStack.length === 0) {
                    return {
                        // Don't pop the stack if we're in repl mode
                        result: options?.repl ? undefined : stack.length > 0 ? popStack() : null,
                        finished: true,
                        state: getVMState(),
                    } satisfies ExecResult
                }
                stackKeepFirstElements(lastCallFrame.stackStart)
                pushStack(null)
                frame = callStack[callStack.length - 1]
                setChunkBytecode()
            }
            nextOp()
            switch (chunkBytecode[frame.ip]) {
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
                    ;[temp, temp2] = unifyComparisonTypes(popStack(), popStack())
                    pushStack(temp === temp2)
                    break
                case Operation.NOT_EQ:
                    ;[temp, temp2] = unifyComparisonTypes(popStack(), popStack())
                    pushStack(temp !== temp2)
                    break
                case Operation.GT:
                    ;[temp, temp2] = unifyComparisonTypes(popStack(), popStack())
                    pushStack(temp > temp2)
                    break
                case Operation.GT_EQ:
                    ;[temp, temp2] = unifyComparisonTypes(popStack(), popStack())
                    pushStack(temp >= temp2)
                    break
                case Operation.LT:
                    ;[temp, temp2] = unifyComparisonTypes(popStack(), popStack())
                    pushStack(temp < temp2)
                    break
                case Operation.LT_EQ:
                    ;[temp, temp2] = unifyComparisonTypes(popStack(), popStack())
                    pushStack(temp <= temp2)
                    break
                case Operation.LIKE:
                    pushStack(like(popStack(), popStack(), false, options?.external?.regex?.match))
                    break
                case Operation.ILIKE:
                    pushStack(like(popStack(), popStack(), true, options?.external?.regex?.match))
                    break
                case Operation.NOT_LIKE:
                    pushStack(!like(popStack(), popStack(), false, options?.external?.regex?.match))
                    break
                case Operation.NOT_ILIKE:
                    pushStack(!like(popStack(), popStack(), true, options?.external?.regex?.match))
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
                    pushStack(regexMatch()(popStack(), temp))
                    break
                case Operation.NOT_REGEX:
                    temp = popStack()
                    pushStack(!regexMatch()(popStack(), temp))
                    break
                case Operation.IREGEX:
                    temp = popStack()
                    pushStack(regexMatch()('(?i)' + popStack(), temp))
                    break
                case Operation.NOT_IREGEX:
                    temp = popStack()
                    pushStack(!regexMatch()('(?i)' + popStack(), temp))
                    break
                case Operation.GET_GLOBAL: {
                    const count = next()
                    const chain = []
                    for (let i = 0; i < count; i++) {
                        chain.push(popStack())
                    }
                    if (chunkGlobals && chain[0] in chunkGlobals && Object.hasOwn(chunkGlobals, chain[0])) {
                        pushStack(convertJSToHog(getNestedValue(chunkGlobals, chain, true)))
                    } else if (
                        options?.asyncFunctions &&
                        chain.length == 1 &&
                        Object.hasOwn(options.asyncFunctions, chain[0]) &&
                        options.asyncFunctions[chain[0]]
                    ) {
                        pushStack(
                            newHogClosure(
                                newHogCallable('async', {
                                    name: chain[0],
                                    argCount: 0, // TODO
                                    upvalueCount: 0,
                                    ip: -1,
                                    chunk: 'async',
                                })
                            )
                        )
                    } else if (chain.length == 1 && chain[0] in ASYNC_STL && Object.hasOwn(ASYNC_STL, chain[0])) {
                        pushStack(
                            newHogClosure(
                                newHogCallable('async', {
                                    name: chain[0],
                                    argCount: ASYNC_STL[chain[0]].maxArgs ?? 0,
                                    upvalueCount: 0,
                                    ip: -1,
                                    chunk: 'async',
                                })
                            )
                        )
                    } else if (chain.length == 1 && chain[0] in STL && Object.hasOwn(STL, chain[0])) {
                        pushStack(
                            newHogClosure(
                                newHogCallable('stl', {
                                    name: chain[0],
                                    argCount: STL[chain[0]].maxArgs ?? 0,
                                    upvalueCount: 0,
                                    ip: -1,
                                    chunk: 'stl',
                                })
                            )
                        )
                    } else if (chain.length == 1 && chain[0] in BYTECODE_STL && Object.hasOwn(BYTECODE_STL, chain[0])) {
                        pushStack(
                            newHogClosure(
                                newHogCallable('stl', {
                                    name: chain[0],
                                    argCount: BYTECODE_STL[chain[0]][0].length,
                                    upvalueCount: 0,
                                    ip: 0,
                                    chunk: `stl/${chain[0]}`,
                                })
                            )
                        )
                    } else {
                        throw new HogVMException(`Global variable not found: ${chain.join('.')}`)
                    }
                    break
                }
                case Operation.POP:
                    popStack()
                    break
                case Operation.CLOSE_UPVALUE:
                    stackKeepFirstElements(stack.length - 1)
                    break
                case Operation.RETURN: {
                    const result = popStack()
                    const lastCallFrame = callStack.pop()
                    if (callStack.length === 0 || !lastCallFrame) {
                        return {
                            result,
                            finished: true,
                            state: { ...getVMState(), bytecodes: {}, stack: [], callStack: [], upvalues: [] },
                        } satisfies ExecResult
                    }
                    const stackStart = lastCallFrame.stackStart
                    stackKeepFirstElements(stackStart)
                    pushStack(result)
                    frame = callStack[callStack.length - 1]
                    setChunkBytecode()
                    continue // resume the loop without incrementing frame.ip
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
                    const name = next()
                    const argCount = next()
                    const upvalueCount = next()
                    const bodyLength = next()
                    const callable = newHogCallable('local', {
                        name,
                        argCount,
                        upvalueCount,
                        ip: frame.ip + 1,
                        chunk: frame.chunk,
                    })
                    pushStack(callable)
                    frame.ip += bodyLength
                    break
                }
                case Operation.CLOSURE: {
                    const callable = popStack()
                    if (!isHogCallable(callable)) {
                        throw new HogVMException(`Invalid callable: ${JSON.stringify(callable)}`)
                    }
                    const upvalueCount = next()
                    const closureUpValues: number[] = []
                    if (upvalueCount !== callable.upvalueCount) {
                        throw new HogVMException(
                            `Invalid upvalue count. Expected ${callable.upvalueCount}, got ${upvalueCount}`
                        )
                    }
                    const stackStart = frame.stackStart
                    for (let i = 0; i < callable.upvalueCount; i++) {
                        const [isLocal, index] = [next(), next()]
                        if (isLocal) {
                            closureUpValues.push(captureUpValue(stackStart + index).id)
                        } else {
                            closureUpValues.push(frame.closure.upvalues[index])
                        }
                    }
                    pushStack(newHogClosure(callable, closureUpValues))
                    break
                }
                case Operation.GET_UPVALUE: {
                    const index = next()
                    if (index >= frame.closure.upvalues.length) {
                        throw new HogVMException(`Invalid upvalue index: ${index}`)
                    }
                    const upvalue = upvaluesById[frame.closure.upvalues[index]]
                    if (!isHogUpValue(upvalue)) {
                        throw new HogVMException(`Invalid upvalue: ${upvalue}`)
                    }
                    if (upvalue.closed) {
                        pushStack(upvalue.value)
                    } else {
                        pushStack(stack[upvalue.location])
                    }
                    break
                }
                case Operation.SET_UPVALUE: {
                    const index = next()
                    if (index >= frame.closure.upvalues.length) {
                        throw new HogVMException(`Invalid upvalue index: ${index}`)
                    }
                    const upvalue = upvaluesById[frame.closure.upvalues[index]]
                    if (!isHogUpValue(upvalue)) {
                        throw new HogVMException(`Invalid upvalue: ${upvalue}`)
                    }
                    if (upvalue.closed) {
                        upvalue.value = popStack()
                    } else {
                        stack[upvalue.location] = popStack()
                    }
                    break
                }
                case Operation.CALL_GLOBAL: {
                    checkTimeout()
                    const name = next()
                    temp = next() // args.length
                    if (name in declaredFunctions && name !== 'toString') {
                        // This is for backwards compatibility. We use a closure on the stack with local functions now.
                        const [funcIp, argLen] = declaredFunctions[name]
                        frame.ip += 1 // advance for when we return
                        if (argLen > temp) {
                            for (let i = temp; i < argLen; i++) {
                                pushStack(null)
                            }
                        }
                        frame = {
                            ip: funcIp,
                            chunk: frame.chunk,
                            stackStart: stack.length - argLen,
                            argCount: argLen,
                            closure: newHogClosure(
                                newHogCallable('local', {
                                    name: name,
                                    argCount: argLen,
                                    upvalueCount: 0,
                                    ip: funcIp,
                                    chunk: frame.chunk,
                                })
                            ),
                        } satisfies CallFrame
                        setChunkBytecode()
                        callStack.push(frame)
                        continue // resume the loop without incrementing frame.ip
                    } else {
                        if (temp > stack.length) {
                            throw new HogVMException('Not enough arguments on the stack')
                        }
                        if (temp > MAX_FUNCTION_ARGS_LENGTH) {
                            throw new HogVMException('Too many arguments')
                        }

                        if (name === 'import') {
                            const args =
                                version === 0
                                    ? Array(temp)
                                          .fill(null)
                                          .map(() => popStack())
                                    : stackKeepFirstElements(stack.length - temp)
                            if (args.length !== 1) {
                                throw new HogVMException(`Function ${name} requires exactly 1 argument`)
                            }
                            frame.ip += 1 // advance for when we return
                            frame = {
                                ip: 0,
                                chunk: args[0],
                                stackStart: stack.length,
                                argCount: 0,
                                closure: newHogClosure(
                                    newHogCallable('local', {
                                        name: args[0],
                                        argCount: 0,
                                        upvalueCount: 0,
                                        ip: 0,
                                        chunk: args[0],
                                    })
                                ),
                            } satisfies CallFrame
                            setChunkBytecode()
                            callStack.push(frame)
                            continue // resume the loop without incrementing frame.ip
                        } else if (
                            options?.functions &&
                            Object.hasOwn(options.functions, name) &&
                            options.functions[name]
                        ) {
                            const args =
                                version === 0
                                    ? Array(temp)
                                          .fill(null)
                                          .map(() => popStack())
                                    : stackKeepFirstElements(stack.length - temp)
                            pushStack(convertJSToHog(options.functions[name](...args.map((v) => convertHogToJS(v)))))
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

                            const args =
                                version === 0
                                    ? Array(temp)
                                          .fill(null)
                                          .map(() => popStack())
                                    : stackKeepFirstElements(stack.length - temp)

                            frame.ip += 1 // resume at the next address after async returns

                            return {
                                result: undefined,
                                finished: false,
                                asyncFunctionName: name,
                                asyncFunctionArgs: args.map((v) => convertHogToJS(v)),
                                state: {
                                    ...getVMState(),
                                    asyncSteps: asyncSteps + 1,
                                },
                            } satisfies ExecResult
                        } else if (name in STL) {
                            const args =
                                version === 0
                                    ? Array(temp)
                                          .fill(null)
                                          .map(() => popStack())
                                    : stackKeepFirstElements(stack.length - temp)
                            pushStack(STL[name].fn(args, name, options))
                        } else if (name in BYTECODE_STL) {
                            const argNames = BYTECODE_STL[name][0]
                            if (argNames.length !== temp) {
                                throw new HogVMException(
                                    `Function ${name} requires exactly ${argNames.length} arguments`
                                )
                            }
                            frame.ip += 1 // advance for when we return
                            frame = {
                                ip: 0,
                                chunk: `stl/${name}`,
                                stackStart: stack.length - temp,
                                argCount: temp,
                                closure: newHogClosure(
                                    newHogCallable('stl', {
                                        name,
                                        argCount: temp,
                                        upvalueCount: 0,
                                        ip: 0,
                                        chunk: `stl/${name}`,
                                    })
                                ),
                            } satisfies CallFrame
                            setChunkBytecode()
                            callStack.push(frame)
                            if (callStack.length > CALLSTACK_LENGTH) {
                                throw new HogVMException(`Call stack exceeded maximum length of ${CALLSTACK_LENGTH}`)
                            }
                            continue // resume the loop without incrementing frame.ip
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
                            chunk: closure.callable.chunk,
                            stackStart: stack.length - closure.callable.argCount,
                            argCount: closure.callable.argCount,
                            closure,
                        } satisfies CallFrame
                        setChunkBytecode()
                        callStack.push(frame)
                        if (callStack.length > CALLSTACK_LENGTH) {
                            throw new HogVMException(`Call stack exceeded maximum length of ${CALLSTACK_LENGTH}`)
                        }
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
                        if (version > 0) {
                            args.reverse()
                        }
                        if (stlFn.maxArgs !== undefined && args.length < stlFn.maxArgs) {
                            for (let i = args.length; i < stlFn.maxArgs; i++) {
                                args.push(null)
                            }
                        }
                        pushStack(stlFn.fn(args, closure.callable.name, options))
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
                            asyncFunctionArgs: args.map((v) => convertHogToJS(v)),
                            state: { ...getVMState(), asyncSteps: asyncSteps + 1 },
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
                        stackKeepFirstElements(stackLen)
                        memUsed -= memStack.splice(stackLen).reduce((acc, val) => acc + val, 0)
                        callStack.splice(callStackLen)
                        pushStack(exception)
                        frame = callStack[callStack.length - 1]
                        setChunkBytecode()
                        frame.ip = catchIp
                        continue // resume the loop without incrementing frame.ip
                    } else {
                        throw new UncaughtHogVMException(exception.type, exception.message, exception.payload)
                    }
                }
                default:
                    throw new HogVMException(
                        `Unexpected node while running bytecode in chunk "${frame.chunk}": ${chunkBytecode[frame.ip]}`
                    )
            }

            // use "continue" to skip this frame.ip auto-increment
            frame.ip++
        }
    } catch (e) {
        return { result: null, finished: false, error: e, state: getVMState() } satisfies ExecResult
    }
}
