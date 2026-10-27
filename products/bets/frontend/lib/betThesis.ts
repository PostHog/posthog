export type ThesisTone = 'text' | 'value' | 'empty'

export interface ThesisPart {
    text: string
    tone: ThesisTone
    keep?: boolean
}

export interface ThesisInput {
    belief: string
    metric: string
    current: string | null
    target: string | null
    direction: 'increase' | 'decrease'
    measured: boolean
    guardrails: string[]
    budget: string | null
    repository: string
}

const BELIEF_LIMIT = 180

function beliefClause(belief: string): string {
    const plain = belief
        .replace(/\s+/g, ' ')
        .trim()
        .replace(/^(we|i) (believe|think|bet)( that)?\s+/i, '')
        .replace(/^if\s+/i, '')
        .replace(/([.!?])\s+[A-Z].*$/, '$1')
        .replace(/,?\s+because\b.*$/i, '')
        .replace(/[.!?;:,\s]+$/, '')
    if (!plain) {
        return ''
    }
    const first = plain.split(' ')[0]
    const keepCase = first.length > 1 && /[A-Z]/.test(first.slice(1))
    const cased = keepCase ? plain : plain[0].toLowerCase() + plain.slice(1)
    if (cased.length <= BELIEF_LIMIT) {
        return cased
    }
    const cut = cased.slice(0, BELIEF_LIMIT)
    return `${cut.slice(0, cut.lastIndexOf(' ') > 0 ? cut.lastIndexOf(' ') : BELIEF_LIMIT)}…`
}

function list(names: string[]): string {
    return names.length < 3 ? names.join(' and ') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

export function betThesis(input: ThesisInput): ThesisPart[] {
    const text = (value: string): ThesisPart => ({ text: value, tone: 'text' })
    const value = (filled: string | null, empty: string, keep = false): ThesisPart =>
        filled
            ? { text: filled, tone: 'value', keep: keep && filled.length <= 32 }
            : { text: empty, tone: 'empty', keep: true }
    const belief = beliefClause(input.belief)
    const parts: ThesisPart[] = belief
        ? [text('If we are right that '), value(belief, ''), text(', then ')]
        : [text('If '), value(null, 'your belief'), text(' is right, then ')]
    parts.push(value(input.metric, 'your metric'))
    if (input.current !== null) {
        parts.push(text(' moves from '), value(input.current, 'now', true), text(' to '))
    } else if (input.measured) {
        parts.push(text(input.direction === 'decrease' ? ' falls to ' : ' rises to '))
    } else {
        parts.push(text(' moves from its current value to '))
    }
    parts.push(value(input.target, 'your target', true))
    if (input.guardrails.length) {
        parts.push(
            text(', while '),
            value(list(input.guardrails), ''),
            text(input.guardrails.length > 1 ? ' do not get worse' : ' does not get worse')
        )
    }
    parts.push(text('. Bets can spend up to '), value(input.budget, 'your budget', true), text(' to test ideas in '))
    parts.push(value(input.repository, 'your repository', true), text('.'))
    return parts
}

const SUBJECT_END =
    /^(will|would|can|could|should|may|might|is|are|was|were|makes?|helps?|keeps?|gets?|leads?|increases?|reduces?|improves?|drives?|lets?|means?|raises?|lowers?|cuts?|brings?|turns?)$/i
const NAME_WORDS = 6
const TRAILING_WORDS = /^(of|the|a|an|to|for|and|or|in|on|with|who|that|which|at|by|from)$/i

export function nameFromBelief(belief: string): string {
    const clause = beliefClause(belief).replace(/…$/, '').split(/[,;:]/)[0]
    const words = clause.split(' ').filter(Boolean)
    const end = words.findIndex((word, index) => index > 0 && SUBJECT_END.test(word))
    const subject = (end > 1 && end <= 8 ? words.slice(0, end) : words.slice(0, NAME_WORDS)).filter(
        (word, index) => index > 0 || !/^(a|an|the)$/i.test(word)
    )
    while (subject.length > 1 && TRAILING_WORDS.test(subject[subject.length - 1])) {
        subject.pop()
    }
    const name = subject.join(' ')
    return name ? name[0].toUpperCase() + name.slice(1) : ''
}
