import { inlineSegments } from './todayReportPresentation'

export interface TodayClause {
    start: number
    end: number
    text: string
    words: number
}

const SENTENCES = new Intl.Segmenter('en', { granularity: 'sentence' })
const WORDS = new Intl.Segmenter('en', { granularity: 'word' })
const IN_PHRASE = new Set([
    "'",
    '’',
    '‘',
    '-',
    '.',
    '/',
    '_',
    '"',
    '“',
    '”',
    '`',
    '$',
    '€',
    '£',
    '%',
    '#',
    '@',
    '*',
    '+',
    '=',
])
const CLAUSE_OPENERS = new Set([
    'because',
    'since',
    'so',
    'but',
    'and',
    'or',
    'which',
    'while',
    'when',
    'after',
    'until',
    'unless',
    'although',
    'though',
    'whereas',
])
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
const MAX_MARKS_PER_REPORT = 2
export const EXPANSION_QUESTION = 'Answer true if the sentence explains the marked part in more detail.'

export type TodayReadingRole = 'problem' | 'cause' | 'fix'
export const READING_LABELS = ['problem', 'cause', 'fix', 'detail']
export const READING_QUESTION =
    'What does this part tell the reader? problem: what goes wrong or who is hurt. cause: why it happens. fix: what to change. detail: anything else, such as numbers, background, tests, or follow-ups.'

export interface TodayKeyClauseRequest {
    text: string
    roles: TodayReadingRole[]
}

export interface TodayKeyClause extends TodayClause {
    role: TodayReadingRole
    confidence: number
    expansion: string[]
}

export interface TodayClauseRole {
    label: string
    probability: number
}

interface Word {
    start: number
    end: number
    text: string
}

function sentenceWords(sentence: string, offset: number): (Word | null)[] {
    const tokens: (Word | null)[] = []
    for (const segment of WORDS.segment(sentence)) {
        const text = segment.segment.trim()
        if (segment.isWordLike) {
            tokens.push({ start: offset + segment.index, end: offset + segment.index + segment.segment.length, text })
        } else if (text && !IN_PHRASE.has(text)) {
            tokens.push(null)
        }
    }
    return tokens
}

/** Splits text into clauses at its punctuation, and before a joining word that opens a new clause. */
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
                if (opensClause && current.length >= MIN_SIDE_WORDS && run.length - index >= MIN_SIDE_WORDS) {
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

/** The state Jev reads to label one clause, with the whole text around it. */
export function clauseRoleInput(text: string, clause: TodayClause): string {
    return `Text:\n${text}\n\nPart of the text:\n${clause.text}`
}

function isSureRole(
    label: TodayClauseRole | null,
    role: TodayReadingRole,
    clause: TodayClause
): label is TodayClauseRole {
    return (
        label !== null &&
        label.label === role &&
        label.probability >= MIN_ROLE_PROBABILITY &&
        clause.words <= MAX_KEY_CLAUSE_WORDS
    )
}

/** For each role a text asks for, the clause Jev labelled with it most surely, when it is sure enough and short. */
export function readingGuide(
    clauses: TodayClause[],
    roles: TodayReadingRole[],
    labelled: (TodayClauseRole | null)[]
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

/** The text a reader sees for a piece of inline markdown, which is what clause offsets point into. */
export function renderedText(markdown: string): string {
    return inlineSegments(markdown)
        .map((segment) => segment.text)
        .join('')
}

/** The report's own sentences outside the text a mark sits in, which a card can quote to explain the mark. */
export function reportSentences(summary: string, shown: string[]): string[] {
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
            if (
                words >= MIN_SENTENCE_WORDS &&
                !shown.some((part) => part.includes(value)) &&
                !sentences.includes(value)
            ) {
                sentences.push(value)
            }
        }
    }
    return sentences.slice(0, MAX_REPORT_SENTENCES)
}

export function expansionInput(clause: TodayClause, sentence: string): string {
    return `Marked part:\n${clause.text}\n\nSentence from the report:\n${sentence}`
}

/** The sentences that explain a mark best, in the order the report gives them. */
export function expansionFor(sentences: string[], probabilities: (number | null)[]): string[] {
    const ranked = sentences
        .map((sentence, index) => ({ sentence, index, probability: probabilities[index] ?? 0 }))
        .filter((candidate) => candidate.probability >= MIN_EXPANSION_PROBABILITY)
        .sort((first, second) => second.probability - first.probability)
        .filter((candidate, rank) => rank === 0 || candidate.probability >= MIN_SECOND_EXPANSION_PROBABILITY)
        .slice(0, MAX_EXPANSION_SENTENCES)
    return ranked.sort((first, second) => first.index - second.index).map((candidate) => candidate.sentence)
}

/** The marks worth showing: only ones the report explains further, and at most a couple, so the page stays calm. */
export function marksWorthShowing(marks: TodayKeyClause[]): Set<TodayKeyClause> {
    return new Set(
        marks
            .filter((mark) => mark.expansion.length > 0)
            .sort((first, second) => second.confidence - first.confidence)
            .slice(0, MAX_MARKS_PER_REPORT)
    )
}
