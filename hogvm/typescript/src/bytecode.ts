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
    TRUE = 25,
    FALSE = 26,
    NULL = 27,
    STRING = 28,
    INTEGER = 29,
    FLOAT = 30,
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

    for (let i = 1; i < bytecode.length; i++) {
        switch (bytecode[i]) {
            case undefined:
                return stack.pop()
            case Operation.STRING:
                stack.push(bytecode[++i])
                break
            case Operation.FLOAT:
                stack.push(bytecode[++i])
                break
            case Operation.INTEGER:
                stack.push(bytecode[++i])
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
                stack.push(!stack.pop())
                break
            case Operation.AND:
                stack.push(
                    Array(bytecode[++i])
                        .fill(null)
                        .map(() => stack.pop())
                        .every(Boolean)
                )
                break
            case Operation.OR:
                stack.push(
                    Array(bytecode[++i])
                        .fill(null)
                        .map(() => stack.pop())
                        .some(Boolean)
                )
                break
            case Operation.PLUS:
                stack.push(Number(stack.pop()) + Number(stack.pop()))
                break
            case Operation.MINUS:
                stack.push(Number(stack.pop()) - Number(stack.pop()))
                break
            case Operation.DIVIDE:
                stack.push(Number(stack.pop()) / Number(stack.pop()))
                break
            case Operation.MULTIPLY:
                stack.push(Number(stack.pop()) * Number(stack.pop()))
                break
            case Operation.MOD:
                stack.push(Number(stack.pop()) % Number(stack.pop()))
                break
            case Operation.EQ:
                stack.push(stack.pop() === stack.pop())
                break
            case Operation.NOT_EQ:
                stack.push(stack.pop() !== stack.pop())
                break
            case Operation.GT:
                stack.push(stack.pop() > stack.pop())
                break
            case Operation.GT_EQ:
                stack.push(stack.pop() >= stack.pop())
                break
            case Operation.LT:
                stack.push(stack.pop() < stack.pop())
                break
            case Operation.LT_EQ:
                stack.push(stack.pop() <= stack.pop())
                break
            case Operation.LIKE:
                stack.push(like(stack.pop(), stack.pop()))
                break
            case Operation.ILIKE:
                stack.push(like(stack.pop(), stack.pop(), true))
                break
            case Operation.NOT_LIKE:
                stack.push(!like(stack.pop(), stack.pop()))
                break
            case Operation.NOT_ILIKE:
                stack.push(!like(stack.pop(), stack.pop(), true))
                break
            case Operation.IN:
                temp = stack.pop()
                stack.push(stack.pop().includes(temp))
                break
            case Operation.NOT_IN:
                temp = stack.pop()
                stack.push(!stack.pop().includes(temp))
                break
            case Operation.REGEX:
                temp = stack.pop()
                stack.push(new RegExp(stack.pop()).test(temp))
                break
            case Operation.NOT_REGEX:
                temp = stack.pop()
                stack.push(!new RegExp(stack.pop()).test(temp))
                break
            case Operation.FIELD:
                const count = bytecode[++i]
                const chain = []
                for (let i = 0; i < count; i++) {
                    chain.push(stack.pop())
                }
                stack.push(getNestedValue(fields, chain))
                break
            case Operation.CALL:
                const name = bytecode[++i]
                const args = Array(bytecode[++i])
                    .fill(null)
                    .map(() => stack.pop())
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

    return stack.pop() ?? null
}
