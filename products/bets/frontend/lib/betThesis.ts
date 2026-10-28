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

const SUBJECT_END =
    /^(will|would|can|could|should|may|might|is|are|was|were|makes?|helps?|keeps?|gets?|leads?|increases?|reduces?|improves?|drives?|lets?|means?|raises?|lowers?|cuts?|brings?|turns?)$/i
const NAME_LIMIT = 60
const TRAILING_WORDS = /^(of|the|a|an|to|for|and|or|in|on|with|who|that|which|at|by|from)$/i

export function nameFromBelief(belief: string): string {
    const clause = beliefClause(belief).replace(/…$/, '').split(/[,;:]/)[0]
    const words = clause.split(' ').filter(Boolean)
    const end = words.findIndex((word, index) => index > 0 && SUBJECT_END.test(word))
    const fitting = words.filter((_, index) => words.slice(0, index + 1).join(' ').length <= NAME_LIMIT)
    const subject = (end > 1 && end <= 8 ? words.slice(0, end) : fitting).filter(
        (word, index) => index > 0 || !/^(a|an|the)$/i.test(word)
    )
    while (subject.length > 1 && TRAILING_WORDS.test(subject[subject.length - 1])) {
        subject.pop()
    }
    const name = subject.join(' ')
    return name ? name[0].toUpperCase() + name.slice(1) : ''
}
