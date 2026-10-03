import { isNotNil, isObject } from 'lib/utils/guards'

import { type SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'

import { withoutCodeBlocks, plainLine, readableExcerpt, firstSentence, SENTENCE_BREAK } from './todayProse'
import { scoutLabel, sourceStyle } from './todaySignalReports'

const BOILERPLATE_LINES = [
    /^new error tracking issue created\b/i,
    /^this error tracking issue is experiencing a spike\b/i,
    /^\(baseline:/i,
    /^-{3,}$/,
    /^(exception|uuid|commit sha|feature|type|value|filename):/i,
    /^anomaly investigation for alert\b/i,
    /^verdict changed from\b/i,
    /^insight:/i,
    /^\[(info|warning|critical)\]/i,
]
const REPO_FILE_ID = /^([\w.-]+\/[\w.-]+):([^\s:]+)$/

export function signalExtra(signal: Pick<SignalNodeApi, 'extra'>): Record<string, unknown> {
    return isObject(signal.extra) ? signal.extra : {}
}

export function textOf(value: unknown): string | null {
    return typeof value === 'string' && value.trim() ? value.trim() : null
}

const HEADLINE_CHARS = 155
const MIN_CLAUSE_CHARS = 120

const QUOTE_MARK = /“|”|(?<=^|\s)["']|["'](?=[\s.,;:!?]|$)/g

function unclosedQuoteStart(text: string): number {
    let open = -1
    for (const match of text.matchAll(QUOTE_MARK)) {
        const index = match.index ?? 0
        const opening = match[0] === '“' || (match[0] !== '”' && (index === 0 || /\s/.test(text[index - 1])))
        open = opening ? index : -1
    }
    return open
}

const TRAILING_PUNCTUATION = /[\s,;:–—-]+$/
const DANGLING_WORDS = new Set(
    'a an the and or but so with to of in on for by at from as into via than that which who'.split(' ')
)

function withoutDanglingWords(text: string): string {
    const words = text.split(' ')
    while (words.length > 1 && DANGLING_WORDS.has(words[words.length - 1].toLowerCase())) {
        words.pop()
    }
    return words.join(' ')
}

function fitHeadline(text: string): string {
    if (text.length <= HEADLINE_CHARS) {
        return text
    }
    const window = text.slice(0, HEADLINE_CHARS)
    const clause = Math.max(window.lastIndexOf(', '), window.lastIndexOf('; '))
    const wordEnd = clause >= MIN_CLAUSE_CHARS ? clause : window.lastIndexOf(' ')
    const cut = text.slice(0, wordEnd > 0 ? wordEnd : HEADLINE_CHARS)
    const quoteStart = unclosedQuoteStart(cut)
    const body = quoteStart > MIN_CLAUSE_CHARS / 2 ? cut.slice(0, quoteStart) : cut
    return `${withoutDanglingWords(body.replace(TRAILING_PUNCTUATION, '')).replace(TRAILING_PUNCTUATION, '')}…`
}

function isBoilerplate(line: string): boolean {
    return BOILERPLATE_LINES.some((pattern) => pattern.test(line))
}

export function signalHeadline(signal: Pick<SignalNodeApi, 'content'>): string {
    const withoutCode = withoutCodeBlocks(signal.content)
    for (const raw of withoutCode.split('\n')) {
        const line = plainLine(raw)
        if (!line || isBoilerplate(line)) {
            continue
        }
        return fitHeadline(readableExcerpt(firstSentence(line)))
    }
    return fitHeadline(readableExcerpt(plainLine(signal.content))) || 'Signal'
}

interface TodaySignalDetail {
    lead: string
    rest: string
    facts: string[]
}

const LINK_POINTER_WORDS = 6

function withoutLinkPointers(line: string): string {
    return line
        .split(SENTENCE_BREAK)
        .filter((sentence) => {
            const rest = sentence.replace(/https?:\/\/\S+/g, '').trim()
            return rest === sentence.trim() || rest.split(/\s+/).length > LINK_POINTER_WORDS
        })
        .join(' ')
}

export function signalDetail(
    signal: Pick<SignalNodeApi, 'source_product' | 'source_type' | 'source_id' | 'content' | 'extra'>
): TodaySignalDetail {
    const lines = withoutCodeBlocks(signal.content)
        .split('\n')
        .map((line) => plainLine(withoutLinkPointers(line)))
        .filter((line) => line && !isBoilerplate(line))
    const text = lines.map((line) => (/[.!?:)]$/.test(line) ? line : `${line}.`)).join(' ')
    const lead = firstSentence(text)
    const extra = signalExtra(signal)
    const facts = [
        signal.source_product === 'pganalyze' ? textOf(extra.server_name) : null,
        signal.source_product === 'pganalyze' && textOf(extra.severity) ? `${textOf(extra.severity)} severity` : null,
        ...signalMetaParts(signal),
    ].filter(isNotNil)
    return {
        lead: readableExcerpt(lead || plainLine(signal.content)),
        rest: readableExcerpt(text.slice(lead.length).trim()),
        facts,
    }
}

export function isPullRequest(signal: Pick<SignalNodeApi, 'source_type' | 'extra'>): boolean {
    const extra = signalExtra(signal)
    return /pull/i.test(signal.source_type) || typeof extra.pull_request === 'object' || 'merged_at' in extra
}

function signalMetaParts(
    signal: Pick<SignalNodeApi, 'source_product' | 'source_type' | 'source_id' | 'extra'>
): string[] {
    const extra = signalExtra(signal)
    const parts: (string | null)[] = []
    switch (signal.source_product) {
        case 'github': {
            const number = typeof extra.number === 'number' ? `#${extra.number}` : null
            parts.push(number ? `${isPullRequest(signal) ? 'Pull request' : 'Issue'} ${number}` : null)
            break
        }
        case 'conversations':
        case 'zendesk': {
            parts.push(typeof extra.ticket_number === 'number' ? `Ticket #${extra.ticket_number}` : null)
            break
        }
        case 'signals_scout': {
            parts.push(signalCodeFile(signal)?.path.split('/').pop() ?? null)
            break
        }
    }
    return parts.filter(isNotNil)
}

export function signalMeta(
    signal: Pick<SignalNodeApi, 'source_product' | 'source_type' | 'source_id' | 'extra'>
): string {
    return signalMetaParts(signal).join(' · ')
}

export interface TodayCodeFile {
    repo: string
    path: string
}

export function signalCodeFile(signal: Pick<SignalNodeApi, 'source_product' | 'source_id'>): TodayCodeFile | null {
    const file = signal.source_product === 'signals_scout' ? signal.source_id.match(REPO_FILE_ID) : null
    return file ? { repo: file[1], path: file[2] } : null
}

export function githubFileUrl(file: TodayCodeFile): string {
    return `https://github.com/${file.repo}/blob/HEAD/${file.path}`
}

export function signalSourceLabel(signal: Pick<SignalNodeApi, 'source_product' | 'extra'>): string {
    const label = sourceStyle(signal.source_product).label
    if (signal.source_product !== 'signals_scout') {
        return label
    }
    return scoutLabel(textOf(signalExtra(signal).skill_name)) ?? label
}
