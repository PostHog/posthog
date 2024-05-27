import { executeStlFunction } from './stl'

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

export async function exec(
    bytecode: any[],
    fields: Record<string, any> = {},
    functions: Record<string, (...args: any[]) => any> = {},
    asyncFunctions: Record<string, (...args: any[]) => Promise<any>> = {},
    timeout: number = 5
): Promise<any> {
    const startTime = Date.now()
    let temp: any
    const stack: any[] = []
    const callStack: [number, number, number][] = []
    const declaredFunctions: Record<string, [number, number]> = {}
    let ip = 1
    let ops = 0

    if (bytecode.length === 0 || bytecode[0] !== '_h') {
        throw new Error("Invalid HogQL bytecode, must start with '_h'")
    }
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
        if (Date.now() - startTime > timeout * 1000) {
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
                stack.push(getNestedValue(fields, chain))
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
                    return popStack()
                }
            case Operation.GET_LOCAL:
                temp = callStack.length > 0 ? callStack[callStack.length - 1][1] : 0
                stack.push(stack[next() + temp])
                break
            case Operation.SET_LOCAL:
                temp = callStack.length > 0 ? callStack[callStack.length - 1][1] : 0
                stack[next() + temp] = popStack()
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
                if (name === 'toString') {
                    const args = Array(next())
                        .fill(null)
                        .map(() => popStack())
                    stack.push(await executeStlFunction(name, args, timeout))
                } else if (name in declaredFunctions) {
                    const [funcIp, argLen] = declaredFunctions[name]
                    callStack.push([ip + 1, stack.length - argLen, argLen])
                    ip = funcIp
                } else {
                    const args = Array(next())
                        .fill(null)
                        .map(() => popStack())
                    if (functions && functions[name]) {
                        stack.push(functions[name](...args))
                    } else if (asyncFunctions && asyncFunctions[name]) {
                        stack.push(await asyncFunctions[name](...args))
                    } else {
                        stack.push(await executeStlFunction(name, args, timeout))
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
        return null
    }

    return popStack() ?? null
}
