export enum BinaryOperationOp {
    Add = '+',
    Sub = '-',
    Mult = '*',
    Div = '/',
    Mod = '%',
}

export enum CompareOperationOp {
    Eq = '==',
    NotEq = '!=',
    Gt = '>',
    GtE = '>=',
    Lt = '<',
    LtE = '<=',
    Like = 'like',
    ILike = 'ilike',
    NotLike = 'not like',
    NotILike = 'not ilike',
    In = 'in',
    NotIn = 'not in',
    Regex = '=~',
    NotRegex = '!~',
}

export enum Operation {
    AND = 'and',
    OR = 'or',
    NOT = 'not',
    CONSTANT = '',
    CALL = '()',
    FIELD = '.',
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
    const iterator = bytecode[Symbol.iterator]()

    if (iterator.next().value !== '_h') {
        throw new Error("Invalid HogQL bytecode, must start with '_h'")
    }

    for (const symbol of iterator) {
        switch (symbol) {
            case undefined:
                return stack.pop()
            case Operation.CONSTANT:
                stack.push(iterator.next().value)
                break
            case Operation.NOT:
                stack.push(!stack.pop())
                break
            case Operation.AND:
                stack.push(
                    Array(iterator.next().value)
                        .fill(null)
                        .map(() => stack.pop())
                        .every(Boolean)
                )
                break
            case Operation.OR:
                stack.push(
                    Array(iterator.next().value)
                        .fill(null)
                        .map(() => stack.pop())
                        .some(Boolean)
                )
                break
            case BinaryOperationOp.Add:
                stack.push(Number(stack.pop()) + Number(stack.pop()))
                break
            case BinaryOperationOp.Sub:
                stack.push(Number(stack.pop()) - Number(stack.pop()))
                break
            case BinaryOperationOp.Div:
                stack.push(Number(stack.pop()) / Number(stack.pop()))
                break
            case BinaryOperationOp.Mult:
                stack.push(Number(stack.pop()) * Number(stack.pop()))
                break
            case BinaryOperationOp.Mod:
                stack.push(Number(stack.pop()) % Number(stack.pop()))
                break
            case CompareOperationOp.Eq:
                stack.push(stack.pop() === stack.pop())
                break
            case CompareOperationOp.NotEq:
                stack.push(stack.pop() !== stack.pop())
                break
            case CompareOperationOp.Gt:
                stack.push(stack.pop() > stack.pop())
                break
            case CompareOperationOp.GtE:
                stack.push(stack.pop() >= stack.pop())
                break
            case CompareOperationOp.Lt:
                stack.push(stack.pop() < stack.pop())
                break
            case CompareOperationOp.LtE:
                stack.push(stack.pop() <= stack.pop())
                break
            case CompareOperationOp.Like:
                stack.push(like(stack.pop(), stack.pop()))
                break
            case CompareOperationOp.ILike:
                stack.push(like(stack.pop(), stack.pop(), true))
                break
            case CompareOperationOp.NotLike:
                stack.push(!like(stack.pop(), stack.pop()))
                break
            case CompareOperationOp.NotILike:
                stack.push(!like(stack.pop(), stack.pop(), true))
                break
            case CompareOperationOp.In:
                temp = stack.pop()
                stack.push(stack.pop().includes(temp))
                break
            case CompareOperationOp.NotIn:
                temp = stack.pop()
                stack.push(!stack.pop().includes(temp))
                break
            case CompareOperationOp.Regex:
                temp = stack.pop()
                stack.push(new RegExp(stack.pop()).test(temp))
                break
            case CompareOperationOp.NotRegex:
                temp = stack.pop()
                stack.push(!new RegExp(stack.pop()).test(temp))
                break
            case Operation.FIELD:
                const count = iterator.next().value
                const chain = []
                for (let i = 0; i < count; i++) {
                    chain.push(stack.pop())
                }
                stack.push(getNestedValue(fields, chain))
                break
            case Operation.CALL:
                const name = iterator.next().value
                const args = Array(iterator.next().value)
                    .fill(null)
                    .map(() => stack.pop())
                if (name === 'concat') {
                    stack.push(args.map((arg) => toConcatArg(arg)).join(''))
                } else if (name === 'match') {
                    stack.push(new RegExp(args[1]).test(args[0]))
                } else {
                    throw new Error(`Unsupported function call: ${name}`)
                }
                break
            default:
                throw new Error(`Unexpected node while running bytecode: ${symbol}`)
        }
    }

    return stack.pop() ?? null
}
