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
}

function like(string: string, pattern: string, caseInsensitive = false): boolean {
    pattern = String(pattern)
        .replaceAll(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&')
        .replaceAll('%', '.*')
    return new RegExp(pattern, caseInsensitive ? 'i' : undefined).test(string)
}

function getNestedValue(obj: any, chain: any[]): any {
    for (const key of chain) {
        if (typeof key === 'number') {
            obj = obj[key]
        } else {
            obj = obj[key] ?? null
        }
    }
    return obj
}

function toConcatArg(arg: any): string {
    return arg === null ? '' : String(arg)
}

export function executeHogQLBytecode(bytecode: any[], fields: Record<string, any>): any {
    let temp: any
    const stack: any[] = []

    if (bytecode.length === 0 || bytecode[0] !== '_h') {
        throw new Error("Invalid HogQL bytecode, must start with '_h'")
    }
    function popStack(): any {
        if (stack.length === 0) {
            throw new Error('Invalid HogQL bytecode, stack is empty')
        }
        return stack.pop()
    }

    let i = 1
    function next(): any {
        if (i >= bytecode.length - 1) {
            throw new Error('Unexpected end of bytecode')
        }
        return bytecode[++i]
    }

    for (; i < bytecode.length; i++) {
        switch (bytecode[i]) {
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
            case Operation.FIELD:
                const count = next()
                const chain = []
                for (let i = 0; i < count; i++) {
                    chain.push(popStack())
                }
                stack.push(getNestedValue(fields, chain))
                break
            case Operation.CALL:
                const name = next()
                const args = Array(next())
                    .fill(null)
                    .map(() => popStack())
                if (name === 'concat') {
                    stack.push(args.map((arg) => toConcatArg(arg)).join(''))
                } else if (name === 'match') {
                    stack.push(new RegExp(args[1]).test(args[0]))
                } else if (name == 'toString' || name == 'toUUID') {
                    stack.push(String(args[0] ?? null))
                } else if (name == 'toInt') {
                    const value = parseInt(args[0])
                    stack.push(isNaN(value) ? null : value)
                } else if (name == 'toFloat') {
                    const value = parseFloat(args[0])
                    stack.push(isNaN(value) ? null : value)
                } else {
                    throw new Error(`Unsupported function call: ${name}`)
                }
                break
            default:
                throw new Error(`Unexpected node while running bytecode: ${bytecode[i]}`)
        }
    }

    if (stack.length > 1) {
        throw new Error('Invalid bytecode. More than one value left on stack')
    }

    return popStack() ?? null
}
