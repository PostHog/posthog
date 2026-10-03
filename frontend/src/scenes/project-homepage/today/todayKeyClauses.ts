import type { JevClient, JevPick } from './todayJev'
import { renderedText } from './todayProse'

interface TodayClause {
    start: number
    end: number
    text: string
    words: number
}

const SENTENCES = new Intl.Segmenter('en', { granularity: 'sentence' })
const WORDS = new Intl.Segmenter('en', { granularity: 'word' })
const IN_PHRASE = new Set(`'’‘-./_"“”\`$€£%#@*+=`)
const DASHES = new Set(['–', '—'])
const CLAUSE_OPENERS = new Set(
    'because since so but and or which while when after until unless although though whereas'.split(' ')
)
const MIN_SIDE_WORDS = 3
const MIN_CLAUSE_WORDS = 2
const MAX_CLAUSES = 15
const MIN_ROLE_PROBABILITY = 0.75
const MAX_KEY_CLAUSE_WORDS = 16
const MIN_SENTENCE_WORDS = 6
const MAX_REPORT_SENTENCES = 25
const MAX_EXPANSION_SENTENCES = 2
const MIN_EXPANSION_PROBABILITY = 0.6
const MIN_SECOND_EXPANSION_PROBABILITY = 0.75
const MAX_KEY_CLAUSES = 2
const EXPANSION_QUESTION = 'Answer true if the sentence explains the marked part in more detail.'

export type TodayClauseRole = 'problem' | 'cause' | 'fix'
const ROLE_LABELS = ['problem', 'cause', 'fix', 'detail']
const ROLE_QUESTION =
    'What does this part tell the reader? problem: what goes wrong or who is hurt. cause: why it happens. fix: what to change. detail: anything else, such as numbers, background, tests, or follow-ups.'

export interface TodayKeyClauseRequest {
    text: string
    roles: TodayClauseRole[]
}

export interface TodayKeyClause extends TodayClause {
    role: TodayClauseRole
    confidence: number
    expansion: string[]
}

interface Word {
    start: number
    end: number
    text: string
}

function joinsWords(sentence: string, segment: Intl.SegmentData): boolean {
    const before = sentence[segment.index - 1] ?? ' '
    const after = sentence[segment.index + segment.segment.length] ?? ' '
    return IN_PHRASE.has(segment.segment) || (DASHES.has(segment.segment) && !/\s/.test(before + after))
}

function sentenceWords(sentence: string, offset: number): (Word | null)[] {
    const tokens: (Word | null)[] = []
    for (const segment of WORDS.segment(sentence)) {
        const text = segment.segment.trim()
        if (segment.isWordLike) {
            tokens.push({ start: offset + segment.index, end: offset + segment.index + segment.segment.length, text })
        } else if (text && !joinsWords(sentence, segment)) {
            tokens.push(null)
        }
    }
    return tokens
}

export function textClauses(text: string): TodayClause[] {
    const clauses: TodayClause[] = []
    const push = (words: Word[]): void => {
        if (words.length >= MIN_CLAUSE_WORDS) {
            const start = words[0].start
            const end = words[words.length - 1].end
            clauses.push({ start, end, text: text.slice(start, end), words: words.length })
        }
    }
    for (const sentence of SENTENCES.segment(text)) {
        const runs: Word[][] = [[]]
        for (const token of sentenceWords(sentence.segment, sentence.index)) {
            if (token) {
                runs[runs.length - 1].push(token)
            } else {
                runs.push([])
            }
        }
        for (const run of runs) {
            let current: Word[] = []
            run.forEach((word, index) => {
                const opensClause = CLAUSE_OPENERS.has(word.text) && word.text === word.text.toLowerCase()
                const bothSidesLong = current.length >= MIN_SIDE_WORDS && run.length - index >= MIN_SIDE_WORDS
                if (opensClause && bothSidesLong) {
                    push(current)
                    current = []
                }
                current.push(word)
            })
            push(current)
        }
    }
    return clauses.slice(0, MAX_CLAUSES)
}

function clauseRoleInput(text: string, clause: TodayClause): string {
    return `Text:\n${text}\n\nPart of the text:\n${clause.text}`
}

function isSureRole(label: JevPick | null, role: TodayClauseRole, clause: TodayClause): label is JevPick {
    return (
        label !== null &&
        label.label === role &&
        label.probability >= MIN_ROLE_PROBABILITY &&
        clause.words <= MAX_KEY_CLAUSE_WORDS
    )
}

function pickKeyClauses(
    clauses: TodayClause[],
    roles: TodayClauseRole[],
    labelled: (JevPick | null)[]
): TodayKeyClause[] {
    const guide: TodayKeyClause[] = []
    for (const role of roles) {
        let best: TodayKeyClause | null = null
        for (const [index, clause] of clauses.entries()) {
            const label = labelled[index] ?? null
            if (isSureRole(label, role, clause) && (!best || label.probability > best.confidence)) {
                best = { ...clause, role, confidence: label.probability, expansion: [] }
            }
        }
        if (best) {
            guide.push(best)
        }
    }
    return guide.sort((first, second) => first.start - second.start)
}

function reportSentences(summary: string, shown: string[]): string[] {
    const seen = new Set(shown.map((text) => text.trim()))
    const sentences: string[] = []
    for (const line of summary.split('\n')) {
        const text = renderedText(line).trim()
        if (!text || seen.has(text)) {
            continue
        }
        for (const sentence of SENTENCES.segment(text)) {
            const value = sentence.segment.trim()
            const words = [...WORDS.segment(value)].filter((segment) => segment.isWordLike).length
            const alreadyRead = shown.some((part) => part.includes(value)) || sentences.includes(value)
            if (words >= MIN_SENTENCE_WORDS && !alreadyRead) {
                sentences.push(value)
            }
        }
    }
    return sentences.slice(0, MAX_REPORT_SENTENCES)
}

function expansionInput(clause: TodayClause, sentence: string): string {
    return `Marked part:\n${clause.text}\n\nSentence from the report:\n${sentence}`
}

function expansionFor(sentences: string[], probabilities: (number | null)[]): string[] {
    const ranked = sentences
        .map((sentence, index) => ({ sentence, index, probability: probabilities[index] ?? 0 }))
        .filter((candidate) => candidate.probability >= MIN_EXPANSION_PROBABILITY)
        .sort((first, second) => second.probability - first.probability)
        .filter((candidate, rank) => rank === 0 || candidate.probability >= MIN_SECOND_EXPANSION_PROBABILITY)
        .slice(0, MAX_EXPANSION_SENTENCES)
    return ranked.sort((first, second) => first.index - second.index).map((candidate) => candidate.sentence)
}

function keyClausesWorthShowing(marks: TodayKeyClause[]): Set<TodayKeyClause> {
    return new Set(
        marks
            .filter((mark) => mark.expansion.length > 0)
            .sort((first, second) => second.confidence - first.confidence)
            .slice(0, MAX_KEY_CLAUSES)
    )
}

function regroup<T>(flat: T[], groups: unknown[][]): T[][] {
    let start = 0
    return groups.map((group) => flat.slice(start, (start += group.length)))
}

async function withExpansions(
    keyClauses: TodayKeyClause[],
    sentences: string[],
    jev: JevClient
): Promise<TodayKeyClause[]> {
    const answers = await jev.yes(
        keyClauses.flatMap((keyClause) => sentences.map((sentence) => expansionInput(keyClause, sentence))),
        EXPANSION_QUESTION
    )
    const perClause = regroup(
        answers,
        keyClauses.map(() => sentences)
    )
    return keyClauses.map((keyClause, index) => ({
        ...keyClause,
        expansion: expansionFor(sentences, perClause[index]),
    }))
}

export async function findKeyClauses(
    requests: TodayKeyClauseRequest[],
    summary: string,
    jev: JevClient
): Promise<Record<string, TodayKeyClause[]>> {
    const sentences = reportSentences(
        summary,
        requests.map((request) => request.text)
    )
    if (!sentences.length) {
        return Object.fromEntries(requests.map((request) => [request.text, []]))
    }
    const prepared = requests.map((request) => ({ ...request, clauses: textClauses(request.text) }))
    const inputs = prepared.flatMap((request) => request.clauses.map((clause) => clauseRoleInput(request.text, clause)))
    const roles = regroup(
        await jev.choice(inputs, ROLE_QUESTION, ROLE_LABELS),
        prepared.map((request) => request.clauses)
    )
    const picked = prepared.map((request, index) => pickKeyClauses(request.clauses, request.roles, roles[index]))
    const expanded = regroup(await withExpansions(picked.flat(), sentences, jev), picked)
    const shown = keyClausesWorthShowing(expanded.flat())
    return Object.fromEntries(
        requests.map((request, index) => [request.text, expanded[index].filter((keyClause) => shown.has(keyClause))])
    )
}
