const LABEL_LISTS = new Set(['by', 'without', 'on', 'ignoring', 'group_left', 'group_right'])
// Operators and modifiers that follow an operand, so a metric of the same name reads as one where an operand starts.
const AFTER_OPERAND = new Set([
    'and',
    'or',
    'unless',
    'offset',
    'keep_metric_names',
    'if',
    'ifnot',
    'default',
    'atan2',
    'limit',
    'prefix',
    'group_left',
    'group_right',
])
const ANYWHERE = new Set(['bool', 'inf', 'nan'])
const WORD = /[a-zA-Z_:][a-zA-Z0-9_:.]*/y
const NUMBER = /[0-9.][0-9.a-zA-Z_]*(?:[eE][+-]?[0-9]+)?/y

function afterString(expr: string, from: number): number {
    const quote = expr[from]
    let at = from + 1
    while (at < expr.length && expr[at] !== quote) {
        at += expr[at] === '\\' ? 2 : 1
    }
    return at + 1
}

function afterGroup(expr: string, from: number, open: string, close: string): number {
    let depth = 0
    for (let at = from; at < expr.length; ) {
        const char = expr[at]
        if (char === '"' || char === "'" || char === '`') {
            at = afterString(expr, at)
            continue
        }
        depth += char === open ? 1 : char === close ? -1 : 0
        at++
        if (depth === 0) {
            return at
        }
    }
    return expr.length
}

function match(pattern: RegExp, expr: string, at: number): string | undefined {
    pattern.lastIndex = at
    return pattern.exec(expr)?.[0]
}

const nextNonSpace = (expr: string, from: number): number => from + (/^\s*/.exec(expr.slice(from))?.[0].length ?? 0)

export function selectorsOf(expr: string): string[] {
    const selectors: string[] = []
    let afterOperand = false
    for (let at = 0; at < expr.length; ) {
        const char = expr[at]
        if (char === '"' || char === "'" || char === '`') {
            at = afterString(expr, at)
            afterOperand = true
        } else if (char === '[') {
            at = afterGroup(expr, at, '[', ']')
            afterOperand = true
        } else if (char === '{') {
            const end = afterGroup(expr, at, '{', '}')
            selectors.push(expr.slice(at, end))
            at = end
            afterOperand = true
        } else if (/[0-9.]/.test(char)) {
            at += match(NUMBER, expr, at)?.length ?? 1
            afterOperand = true
        } else {
            const word = match(WORD, expr, at)
            if (word === undefined) {
                afterOperand = char === ')' || (/\s/.test(char) && afterOperand)
                at++
                continue
            }
            const keyword = word.toLowerCase()
            const next = nextNonSpace(expr, at + word.length)
            if (LABEL_LISTS.has(word) && expr[next] === '(') {
                at = afterGroup(expr, next, '(', ')')
                afterOperand = true
            } else if (
                expr[next] === '(' ||
                ANYWHERE.has(keyword) ||
                (afterOperand && AFTER_OPERAND.has(keyword)) ||
                LABEL_LISTS.has(match(WORD, expr, next) ?? '')
            ) {
                at += word.length
                afterOperand = false
            } else if (expr[next] === '{') {
                const end = afterGroup(expr, next, '{', '}')
                selectors.push(`${word}${expr.slice(next, end)}`)
                at = end
                afterOperand = true
            } else {
                selectors.push(word)
                at += word.length
                afterOperand = true
            }
        }
    }
    return [...new Set(selectors)]
}
