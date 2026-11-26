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
    'prefix',
])
const LITERALS = new Set(['inf', 'nan'])
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

const DURATION = /-?(?:[0-9.]+(?:ms|[smhdwy]))+|-?[0-9.]+/y
const UNIT_SECONDS: Record<string, number> = { ms: 0.001, s: 1, m: 60, h: 3600, d: 86400, w: 604800, y: 31536000 }

export type SelectorRead = { selector: string; offsetSeconds: number }

function secondsOf(duration: string): number {
    const sign = duration.startsWith('-') ? -1 : 1
    const parts = [...duration.matchAll(/([0-9.]+)(ms|[smhdwy])?/g)]
    return sign * parts.reduce((sum, [, amount, unit]) => sum + Number(amount) * UNIT_SECONDS[unit ?? 's'], 0)
}

// The offset modifier that follows position `from`, past an optional range or subquery window.
function offsetAfter(expr: string, from: number): number {
    let at = nextNonSpace(expr, from)
    if (expr[at] === '[') {
        at = nextNonSpace(expr, afterGroup(expr, at, '[', ']'))
    }
    if (match(WORD, expr, at)?.toLowerCase() !== 'offset') {
        return 0
    }
    const duration = match(DURATION, expr, nextNonSpace(expr, at + 'offset'.length))
    return duration === undefined ? 0 : secondsOf(duration)
}

export function selectorsOf(expr: string): string[] {
    return [...new Set(readsOf(expr).map(({ selector }) => selector))]
}

// Each selector with the offset its samples are read at: its own modifier plus that of every subquery around it.
export function readsOf(expr: string): SelectorRead[] {
    const reads: (SelectorRead & { at: number })[] = []
    const opens: number[] = []
    let closed: { open: number; close: number } | undefined
    const add = (selector: string, at: number, end: number): void => {
        reads.push({ selector, at, offsetSeconds: offsetAfter(expr, end) })
    }
    for (let at = 0; at < expr.length; ) {
        const char = expr[at]
        if (char === '"' || char === "'" || char === '`') {
            at = afterString(expr, at)
        } else if (char === '(' || char === ')') {
            if (char === '(') {
                opens.push(at)
            } else if (opens.length > 0) {
                closed = { open: opens.pop()!, close: at }
            }
            at++
        } else if (char === '[') {
            const end = afterGroup(expr, at, '[', ']')
            const window = closed !== undefined && nextNonSpace(expr, closed.close + 1) === at ? closed : undefined
            if (window !== undefined && expr.slice(at, end).includes(':')) {
                const offset = offsetAfter(expr, end)
                reads
                    .filter((read) => read.at > window.open && read.at < window.close)
                    .forEach((read) => (read.offsetSeconds += offset))
            }
            at = end
        } else if (char === '{') {
            const end = afterGroup(expr, at, '{', '}')
            add(expr.slice(at, end), at, end)
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
            const lower = word.toLowerCase()
            const operand =
                !LITERALS.has(lower) && (expr[at + word.length] === '{' || [')', ','].includes(expr[next] ?? ''))
            if (LABEL_LISTS.has(word) && !operand) {
                at = expr[next] === '(' ? afterGroup(expr, next, '(', ')') : at + word.length
            } else if (
                !operand &&
                (expr[next] === '(' ||
                    KEYWORDS.has(lower) ||
                    (lower === 'limit' && /[0-9]/.test(expr[next] ?? '')) ||
                    LABEL_LISTS.has(match(WORD, expr, next) ?? ''))
            ) {
                at += word.length
            } else if (expr[next] === '{') {
                const end = afterGroup(expr, next, '{', '}')
                add(`${word}${expr.slice(next, end)}`, at, end)
                at = end
            } else {
                add(word, at, at + word.length)
                at += word.length
            }
        }
    }
    const unique = new Map(
        reads.map(({ selector, offsetSeconds }) => [`${offsetSeconds} ${selector}`, { selector, offsetSeconds }])
    )
    return [...unique.values()]
}
