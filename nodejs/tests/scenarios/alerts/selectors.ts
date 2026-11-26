const LABEL_LISTS = new Set(['by', 'without', 'on', 'ignoring', 'group_left', 'group_right'])
const KEYWORDS = new Set([
    'and',
    'or',
    'unless',
    'bool',
    'offset',
    'inf',
    'nan',
    'keep_metric_names',
    'if',
    'ifnot',
    'default',
    'atan2',
    'limit',
    'prefix',
])
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
    for (let at = 0; at < expr.length; ) {
        const char = expr[at]
        if (char === '"' || char === "'" || char === '`') {
            at = afterString(expr, at)
        } else if (char === '[') {
            at = afterGroup(expr, at, '[', ']')
        } else if (char === '{') {
            const end = afterGroup(expr, at, '{', '}')
            selectors.push(expr.slice(at, end))
            at = end
        } else if (/[0-9.]/.test(char)) {
            at += match(NUMBER, expr, at)?.length ?? 1
        } else {
            const word = match(WORD, expr, at)
            if (word === undefined) {
                at++
                continue
            }
            const next = nextNonSpace(expr, at + word.length)
            if (LABEL_LISTS.has(word) && expr[next] === '(') {
                at = afterGroup(expr, next, '(', ')')
            } else if (
                expr[next] === '(' ||
                KEYWORDS.has(word.toLowerCase()) ||
                LABEL_LISTS.has(match(WORD, expr, next) ?? '')
            ) {
                at += word.length
            } else if (expr[next] === '{') {
                const end = afterGroup(expr, next, '{', '}')
                selectors.push(`${word}${expr.slice(next, end)}`)
                at = end
            } else {
                selectors.push(word)
                at += word.length
            }
        }
    }
    return [...new Set(selectors)]
}
