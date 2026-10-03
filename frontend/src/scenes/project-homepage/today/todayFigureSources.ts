import { Dayjs, dayjs } from 'lib/dayjs'
import { isNotNil, isObject } from 'lib/utils/guards'

import { type SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'

import {
    numberPattern,
    numbersIn,
    withoutDigitCommas,
    figureAmount,
    TodayFigure,
    UNIT,
    findFigures,
    figuresToMark,
    parseAmount,
} from './todayFigures'
import { inlineSegments, plainLine, proseSentences, readableExcerpt, shortDate } from './todayProse'
import { textOf } from './todaySignalText'

export interface TodayResearchNote {
    text: string
    at: string
    signalId: string | null
}

const RESEARCH_FIELDS: Record<string, string> = {
    priority_judgment: 'explanation',
    actionability_judgment: 'explanation',
    signal_finding: 'data_queried',
    check_scheduled: 'rationale',
    note: 'note',
}

const PLAN_NOTE = /^#+\s*verification plan/i

function textField(content: unknown, key: string): string | null {
    return isObject(content) ? textOf(content[key]) : null
}

export function researchNotes(
    artefacts:
        | readonly { type: string; content: unknown; created_at: string; created_by?: unknown }[]
        | null
        | undefined
): TodayResearchNote[] {
    const seen = new Set<string>()
    const notes: TodayResearchNote[] = []
    const newestFirst = [...(artefacts ?? [])].sort((first, second) =>
        second.created_at.localeCompare(first.created_at)
    )
    for (const artefact of newestFirst) {
        const field = RESEARCH_FIELDS[artefact.type]
        const text = field ? textField(artefact.content, field) : null
        const signalId = artefact.type === 'signal_finding' ? textField(artefact.content, 'signal_id') : null
        const key = ['check_scheduled', 'note'].includes(artefact.type) ? null : `${artefact.type}:${signalId ?? ''}`
        if (!text || artefact.created_by || PLAN_NOTE.test(text) || (key && seen.has(key))) {
            continue
        }
        if (key) {
            seen.add(key)
        }
        notes.push({ text, at: artefact.created_at, signalId })
    }
    return notes
}

const COMMON_WORDS = new Set(
    'about across after again also because been before being between both could does doing during each every from have into just more most much only other over same since some still such than that their them then there these they this those through under until very were what when where which while with would your'.split(
        ' '
    )
)

function wordStems(text: string): Set<string> {
    return new Set(
        (text.toLowerCase().match(/[a-z][a-z'-]{3,}/g) ?? [])
            .filter((word) => !COMMON_WORDS.has(word))
            .map((word) => word.slice(0, 5))
    )
}

function overlap(first: Set<string>, second: Set<string>): number {
    let shared = 0
    for (const stem of first) {
        shared += second.has(stem) ? 1 : 0
    }
    return shared
}

const EXCERPT_BEFORE = 120
const EXCERPT_AFTER = 160

const CLAUSE_END = /\)?[,;]\s|\s[—–]\s/g
const CLAUSE_START = /[,;:]\s|\s[—–]\s/g
const EXCERPT_REACH = 130
const CLAUSE_MIN_TAIL = 4

function excerptStart(sentence: string, first: number): number {
    if (first <= EXCERPT_REACH) {
        return 0
    }
    for (const match of sentence.slice(0, first).matchAll(CLAUSE_START)) {
        const index = (match.index ?? 0) + match[0].length
        if (first - index <= EXCERPT_REACH) {
            return index
        }
    }
    return sentence.indexOf(' ', first - EXCERPT_BEFORE) + 1
}

function excerptAround(sentence: string, needles: string[]): string {
    const positions = needles
        .map((needle) => {
            const match = numberPattern(needle).exec(sentence)
            return match ? { start: match.index, end: match.index + match[0].length } : null
        })
        .filter(isNotNil)
    if (!positions.length || sentence.length <= EXCERPT_BEFORE + EXCERPT_AFTER) {
        return sentence
    }
    const first = Math.min(...positions.map((position) => position.start))
    const last = Math.max(...positions.map((position) => position.end))
    const start = excerptStart(sentence, first)
    CLAUSE_END.lastIndex = last + CLAUSE_MIN_TAIL
    const clause = CLAUSE_END.exec(sentence)
    const limit = Math.min(sentence.length, last + EXCERPT_AFTER)
    const wordEnd = limit === sentence.length ? limit : sentence.lastIndexOf(' ', limit)
    const closingParen = clause?.[0].startsWith(')') ? 1 : 0
    const end = clause && clause.index < limit ? clause.index + closingParen : wordEnd
    const body = sentence.slice(start, end).replace(/[\s,;:–—-]+$/, '')
    return `${start > 0 ? '…' : ''}${body}${end < sentence.length && !/[.!?]$/.test(body) ? '…' : ''}`
}

interface WeightedText {
    text: string
    signal: SignalNodeApi | null
    note: TodayResearchNote | null
    weight: number
}

interface TodayFigureMatch {
    score: number
    source: WeightedText
    sentence: string
    shownValues: string[]
    parts: string[] | null
    exact?: string | null
}

interface FigureClaim {
    amount: number
    pattern: RegExp
    stem: string | null
    needsNoun: boolean
    stems: Set<string>
    approximate: boolean
    shown: string
}

interface TodayFigureEvidence {
    signals: SignalNodeApi[]
    research: TodayResearchNote[]
    summary: string | null | undefined
}

interface TodayFigureContext extends TodayFigureEvidence {
    shownText: string
}

interface TodayFigureExcerpt {
    excerpt: string
    values: string[]
    parts: string[] | null
    exact?: string | null
}

type TodayFigureSource =
    | ({ kind: 'signal'; signal: SignalNodeApi } & TodayFigureExcerpt)
    | ({ kind: 'research'; note: TodayResearchNote; signal: SignalNodeApi | null } & TodayFigureExcerpt)
    | ({ kind: 'report' } & TodayFigureExcerpt)

const MIN_SUM = 10
const MIN_SUM_OVERLAP = 2
const MIN_CONTEXT_OVERLAP = 3

function addsUpTo(sentence: string, target: number): string[] | null {
    const values = numbersIn(sentence)
        .filter((figure) => !figure.text.includes('%') && !/[–-]/.test(figure.text))
        .map((figure) => figure.value)
    for (let size = 2; size <= 3; size++) {
        for (let index = 0; index + size <= values.length; index++) {
            const parts = values.slice(index, index + size)
            const sum = parts.reduce((total, part) => total + parseAmount(part), 0)
            if (sum === target) {
                return parts
            }
        }
    }
    return null
}

const LOWERCASE_SENTENCE_BREAK = /(?<=\b[a-z]{3,}[.!?])\s+(?=[a-z])/

const FUNCTION_WORDS = new Set(
    'a across after against an and as at before by for from in into of on or out over per than the to under with'.split(
        ' '
    )
)
const APPROXIMATE_LEAD = /\b(?:about|around|roughly|nearly|almost|approximately|over|under|~)\s*$/i
const APPROXIMATE_TOLERANCE = 0.06

function closeTo(sentence: string, target: number): string | null {
    for (const candidate of numbersIn(sentence)) {
        const amount = figureAmount(candidate)
        if (amount > 0 && Math.abs(amount - target) / target <= APPROXIMATE_TOLERANCE) {
            return candidate.value
        }
    }
    return null
}

function figureClaim(figure: Pick<TodayFigure, 'text' | 'value' | 'noun'>, shownText: string): FigureClaim {
    const amount = figureAmount(figure)
    const unit = figure.text.match(UNIT)?.[1] ?? null
    const unitSuffix = unit && unit !== 'K' && unit !== 'M' ? `\\s?${unit}` : ''
    const noun = figure.noun && !FUNCTION_WORDS.has(figure.noun.toLowerCase()) ? figure.noun : null
    const claim = proseSentences(shownText).find((sentence) => sentence.includes(figure.text)) ?? plainLine(shownText)
    const lead = claim.slice(0, Math.max(0, claim.indexOf(figure.text)))
    return {
        amount,
        pattern: new RegExp(`${numberPattern(figure.value).source}${unitSuffix}`),
        stem: noun && noun.length > 2 ? noun.slice(0, 4).toLowerCase() : null,
        needsNoun: amount < 100 && !unit,
        stems: wordStems(claim),
        approximate: unit === 'K' || unit === 'M' || APPROXIMATE_LEAD.test(lead),
        shown: withoutDigitCommas(plainLine(shownText)),
    }
}

function weightedTexts({ signals, research, summary }: TodayFigureEvidence): WeightedText[] {
    const signalById = new Map(signals.map((signal) => [signal.signal_id, signal]))
    return [
        ...signals.map((signal) => ({ text: signal.content, signal, note: null, weight: 1 })),
        ...research.map((note) => ({
            text: note.text,
            signal: note.signalId ? (signalById.get(note.signalId) ?? null) : null,
            note,
            weight: 0.5,
        })),
        { text: summary ?? '', signal: null, note: null, weight: 0 },
    ]
}

function sentenceMatch(
    figure: Pick<TodayFigure, 'value'>,
    claim: FigureClaim,
    source: WeightedText,
    sentence: string,
    bestScore: number
): TodayFigureMatch | null {
    const shared = Math.min(overlap(claim.stems, wordStems(sentence)), 5)
    const nounScore = claim.stem && sentence.toLowerCase().includes(claim.stem) ? 2 : 0
    const directScore = 10 + nounScore + shared * 0.5 + source.weight
    if (claim.pattern.test(sentence)) {
        const contextHolds =
            !claim.needsNoun || nounScore > 0 || shared >= (claim.stem ? MIN_CONTEXT_OVERLAP : MIN_SUM_OVERLAP)
        return contextHolds ? { source, sentence, score: directScore, shownValues: [figure.value], parts: null } : null
    }
    if (shared < MIN_SUM_OVERLAP) {
        return null
    }
    const near = claim.approximate ? closeTo(sentence, claim.amount) : null
    if (near) {
        const exact = parseAmount(near).toLocaleString('en-US')
        return { source, sentence, score: directScore, shownValues: [near], parts: null, exact }
    }
    const mightBeTotal = claim.amount >= MIN_SUM && bestScore < 10
    const parts = mightBeTotal ? addsUpTo(sentence, claim.amount) : null
    return parts ? { source, sentence, score: shared * 0.5 + source.weight, shownValues: parts, parts } : null
}

function asFigureSource(match: TodayFigureMatch): TodayFigureSource {
    const fields = {
        excerpt: readableExcerpt(excerptAround(match.sentence, match.shownValues)),
        values: match.shownValues,
        parts: match.parts,
        exact: match.exact ?? null,
    }
    const { note, signal } = match.source
    if (note) {
        return { kind: 'research', note, signal, ...fields }
    }
    if (signal) {
        return { kind: 'signal', signal, ...fields }
    }
    return { kind: 'report', ...fields }
}

export function figureSource(
    figure: Pick<TodayFigure, 'text' | 'value' | 'noun'>,
    { shownText, ...evidence }: TodayFigureContext
): TodayFigureSource | null {
    const claim = figureClaim(figure, shownText)
    let best = null as TodayFigureMatch | null
    for (const source of weightedTexts(evidence)) {
        for (const sentence of proseSentences(source.text).flatMap((line) => line.split(LOWERCASE_SENTENCE_BREAK))) {
            const repeatsShownText =
                !source.note && !source.signal && claim.shown.includes(withoutDigitCommas(sentence))
            const match = repeatsShownText ? null : sentenceMatch(figure, claim, source, sentence, best?.score ?? 0)
            if (match && match.score > (best?.score ?? 0)) {
                best = match
            }
        }
    }
    return best ? asFigureSource(best) : null
}

export type TodayFigureCardContent =
    | ({
          kind: 'signal'
          signal: SignalNodeApi
          working?: { expression: string; result: string }
      } & Partial<TodayFigureExcerpt> & { excerpt: string })
    | Exclude<TodayFigureSource, { kind: 'signal' }>
    | {
          kind: 'metric'
          total: string
          at: string | null
          range: { from: string; to: string } | null
          caption: string | null
          window: string | null
          trend: number[] | null
          link: { url: string; label: string } | null
      }
    | { kind: 'none' }

export interface TodayMarkedFigure extends TodayFigure {
    segment: number
    content: TodayFigureCardContent
}

const MAX_MARKS = 4

export function markedFigures(markdown: string, evidence: TodayFigureEvidence): TodayMarkedFigure[] {
    const sourced = inlineSegments(markdown).flatMap((segment, index) =>
        segment.kind === 'text'
            ? findFigures(segment.text).flatMap((figure) => {
                  const source = figureSource(figure, { ...evidence, shownText: markdown })
                  return source ? [{ ...figure, segment: index, content: source }] : []
              })
            : []
    )
    const chosen = figuresToMark(sourced, MAX_MARKS)
    return sourced.filter((figure) => chosen.has(figure))
}

const STALE_AFTER_DAYS = 7

export function daysAgo(date: string, now: Dayjs = dayjs()): number {
    return now.startOf('day').diff(dayjs(date).startOf('day'), 'day')
}

function sourceDate(content: TodayFigureCardContent): string | null {
    switch (content.kind) {
        case 'research':
            return content.note.at
        case 'signal':
            return content.signal.timestamp
        default:
            return null
    }
}

export function staleEvidenceDate(figures: TodayMarkedFigure[], now: Dayjs = dayjs()): string | null {
    const newest = figures
        .map((figure) => sourceDate(figure.content))
        .filter(isNotNil)
        .sort()
        .at(-1)
    return newest && daysAgo(newest, now) > STALE_AFTER_DAYS ? newest : null
}

export function anchorToday(text: string, date: string, now: Dayjs = dayjs()): string {
    return daysAgo(date, now) > 0 ? text.replace(/\btoday\b/gi, (word) => `${word} [${shortDate(date)}]`) : text
}
