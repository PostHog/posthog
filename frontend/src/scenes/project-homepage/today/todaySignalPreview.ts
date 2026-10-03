import { isObject } from 'lib/utils/guards'

import type { RepositoryFileApi } from 'products/business_knowledge/frontend/generated/api.schemas'
import type { SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'

import {
    TodayCodeExcerpt,
    TodayCodeFile,
    codeExcerptCandidates,
    conciseText,
    signalCodeFile,
    signalDestination,
    signalReading,
    signalSlackThread,
} from './todayReportPresentation'

type PreviewSignal = Pick<SignalNodeApi, 'source_product' | 'source_type' | 'source_id' | 'content' | 'extra'>

export interface TodayPreviewLine {
    text: string
    quiet: boolean
}

export interface TodayPreviewLink {
    to: string
    external: boolean
    label: string
}

export interface TodaySignalPreview {
    /** What the row offers before it opens, such as "Show the stack trace". */
    hint: string
    /** The files a scout's finding is about: its own file first, then files it names in the same folder. */
    code: TodayCodeFile[]
    /** A few lines of machine text, such as a stack trace or a query. */
    block: TodayPreviewLine[]
    text: string
    facts: string[]
    open: TodayPreviewLink | null
}

const PREVIEW_CHARS = 240
const MAX_EXCEPTIONS = 4
const MAX_SIBLING_FILES = 2
const FENCED_BLOCK = /```[^\n]*\n([\s\S]*?)(?:```|$)/
const FRAME_LINE = /^(\S+) in (\S+) line (\d+)$/
const IN_APP_PATH = /^(?:posthog|products|ee|common|services|frontend)\//
const SECTION_LABEL = /^\*\*([^*\n]+?):\*\*\s*/
const BARE_FILE_NAME = /`([\w-]+\.[a-z]{1,5})`/gi

function extraOf(signal: Pick<SignalNodeApi, 'extra'>): Record<string, unknown> {
    return isObject(signal.extra) ? (signal.extra as Record<string, unknown>) : {}
}

function text(value: unknown): string | null {
    return typeof value === 'string' && value.trim() ? value.trim() : null
}

function sentenceCase(value: string): string {
    const words = value.replace(/_/g, ' ').trim()
    return `${words.charAt(0).toUpperCase()}${words.slice(1).toLowerCase()}`
}

function readable(signal: PreviewSignal, content: string): string {
    const reading = signalReading({ ...signal, content })
    return [reading.lead, reading.rest].filter(Boolean).join(' ')
}

function paragraphs(content: string): string[] {
    return content
        .split(/\n\s*\n/)
        .map((paragraph) => paragraph.trim())
        .filter(Boolean)
}

/**
 * The exceptions in a stack trace, outermost first, each with the deepest frame in the team's own code.
 * The outermost one is left out when the signal's text already states it, since the row's headline shows it.
 */
export function exceptionChain(content: string): TodayPreviewLine[] {
    const trace = content.match(FENCED_BLOCK)?.[1] ?? ''
    const exceptions: { header: string; frames: { fn: string; path: string; line: string }[] }[] = []
    for (const raw of trace.split('\n')) {
        const line = raw.trim()
        if (!line) {
            continue
        }
        const frame = line.match(FRAME_LINE)
        if (frame && exceptions.length) {
            exceptions[exceptions.length - 1].frames.push({ fn: frame[1], path: frame[2], line: frame[3] })
        } else if (!frame) {
            exceptions.push({ header: line, frames: [] })
        }
    }
    if (!exceptions.some((exception) => exception.frames.length)) {
        return []
    }
    const prose = content.replace(FENCED_BLOCK, '')
    return exceptions.flatMap((exception, index) => {
        if (index > 0 && index < exceptions.length - MAX_EXCEPTIONS + 1) {
            return []
        }
        const own = exception.frames.filter((frame) => IN_APP_PATH.test(frame.path))
        const frame = own[own.length - 1] ?? exception.frames[exception.frames.length - 1]
        const header =
            index === 0
                ? prose.includes(exception.header)
                    ? []
                    : [{ text: exception.header, quiet: false }]
                : [{ text: `Caused by ${exception.header}`, quiet: false }]
        return [
            ...header,
            ...(frame ? [{ text: `  ${frame.path.split('/').pop()}:${frame.line}  ${frame.fn}`, quiet: true }] : []),
        ]
    })
}

/** The query a pganalyze issue is about, as pganalyze shortened it. */
export function pganalyzeQuery(signal: Pick<SignalNodeApi, 'extra'>): string | null {
    const references = extraOf(signal).references
    if (!Array.isArray(references)) {
        return null
    }
    const query = references.find((reference) => isObject(reference) && reference.kind === 'Query')
    return isObject(query) ? text(query.queryText) : null
}

/** The first paragraph after a title line, or the paragraph under a named label such as "Issue". */
export function bodyParagraph(content: string, label?: string): string | null {
    const titleEnd = content.trim().indexOf('\n')
    const body = titleEnd < 0 ? [] : paragraphs(content.trim().slice(titleEnd + 1))
    const labelled = label
        ? body.find((paragraph) => paragraph.match(SECTION_LABEL)?.[1].toLowerCase() === label.toLowerCase())
        : undefined
    const chosen = labelled ?? body.find((paragraph) => !SECTION_LABEL.test(paragraph))
    return chosen ? chosen.replace(SECTION_LABEL, '').trim() || null : null
}

/** Files a scout's finding names in backticks that sit in the same folder as its own file. */
export function codeSiblingFiles(file: TodayCodeFile, content: string): TodayCodeFile[] {
    const folder = file.path.includes('/') ? file.path.slice(0, file.path.lastIndexOf('/') + 1) : ''
    const own = file.path.slice(folder.length)
    const names = [...content.matchAll(BARE_FILE_NAME)].map((match) => match[1]).filter((name) => name !== own)
    return [...new Set(names)]
        .slice(0, MAX_SIBLING_FILES)
        .map((name) => ({ repo: file.repo, path: `${folder}${name}` }))
}

export type TodayCodeFileRead = RepositoryFileApi | null | 'loading' | undefined

export interface TodayChosenExcerpt {
    file: TodayCodeFile
    read: RepositoryFileApi
    excerpt: TodayCodeExcerpt
    candidates: TodayCodeExcerpt[]
}

function distinctMarked(excerpt: TodayCodeExcerpt): number {
    return new Set(excerpt.marks.map((mark) => excerpt.lines[mark.line].slice(mark.start, mark.end))).size
}

/**
 * The file whose excerpt holds the most of the quoted code, the finding's own file on a tie.
 * 'loading' while a candidate is still being read, null when no file holds the quote.
 */
export function chooseCodeExcerpt(
    files: TodayCodeFile[],
    reads: TodayCodeFileRead[],
    identifiers: string[]
): TodayChosenExcerpt | 'loading' | null {
    if (reads.some((read) => read === 'loading' || read === undefined)) {
        return 'loading'
    }
    let best: TodayChosenExcerpt | null = null
    files.forEach((file, index) => {
        const read = reads[index]
        const candidates = read && read !== 'loading' ? codeExcerptCandidates(read.content, identifiers) : []
        const excerpt = candidates[0]
        if (excerpt && (!best || distinctMarked(excerpt) > distinctMarked(best.excerpt))) {
            best = { file, read: read as RepositoryFileApi, excerpt, candidates }
        }
    })
    return best
}

function githubFacts(extra: Record<string, unknown>): string[] {
    const merged = typeof extra.merged_at === 'string'
    const state = merged ? 'Merged' : text(extra.state) ? sentenceCase(text(extra.state) as string) : null
    const author = text(extra.author_login)
    const labels = Array.isArray(extra.labels)
        ? extra.labels
              .map((label) => (isObject(label) ? text(label.name) : text(label)))
              .filter((label): label is string => !!label)
        : []
    return [state, author ? `by ${author}` : null, ...labels].filter((fact): fact is string => !!fact)
}

const CHANNELS: Record<string, string> = { slack: 'Slack', email: 'Email', widget: 'Chat widget' }

function ticketFacts(extra: Record<string, unknown>): string[] {
    const channel = text(extra.channel_source)
    const priority = text(extra.priority)
    const status = text(extra.status)
    return [
        channel ? (CHANNELS[channel] ?? sentenceCase(channel)) : null,
        priority ? `${sentenceCase(priority)} priority` : null,
        status ? sentenceCase(status) : null,
    ].filter((fact): fact is string => !!fact)
}

function anomalyFacts(extra: Record<string, unknown>): string[] {
    const verdict = text(extra.verdict)
    return verdict ? [sentenceCase(verdict)] : []
}

/** The rest of the paragraph a signal's headline opens, so the preview never repeats the headline. */
function findingRest(signal: PreviewSignal): string {
    const lead = signalReading(signal).lead
    for (const line of signal.content.split('\n')) {
        const reading = signalReading({ ...signal, content: line })
        if (lead && reading.lead === lead) {
            return reading.rest
        }
    }
    return ''
}

function previewOf(signal: PreviewSignal): TodaySignalPreview | null {
    const destination = signalDestination(signal)
    if (destination.kind === 'recording') {
        return null
    }
    const extra = extraOf(signal)
    const reading = signalReading(signal)
    const link = destination.kind === 'link' ? destination : null
    const preview: TodaySignalPreview = {
        hint: 'Read in full',
        code: [],
        block: [],
        text: reading.rest,
        facts: reading.facts,
        open: link ? { to: link.to, external: link.external, label: link.label } : null,
    }
    const codeFile = signalCodeFile(signal)
    const slackThread = signalSlackThread(signal)
    switch (signal.source_product) {
        case 'signals_scout':
            if (codeFile) {
                return {
                    ...preview,
                    hint: 'Show the code',
                    code: [codeFile, ...codeSiblingFiles(codeFile, signal.content)],
                    open: {
                        to: `https://github.com/${codeFile.repo}/blob/HEAD/${codeFile.path}`,
                        external: true,
                        label: 'Open on GitHub',
                    },
                }
            }
            if (slackThread) {
                return {
                    ...preview,
                    hint: 'Show what the thread says',
                    open: { to: slackThread, external: true, label: 'Open in Slack' },
                }
            }
            break
        case 'error_tracking': {
            const block = exceptionChain(signal.content)
            return block.length ? { ...preview, hint: 'Show the stack trace', block, text: '' } : null
        }
        case 'pganalyze': {
            const query = pganalyzeQuery(signal)
            return query ? { ...preview, hint: 'Show the query', block: [{ text: query, quiet: false }] } : null
        }
        case 'github': {
            const body = bodyParagraph(signal.content)
            return body
                ? {
                      ...preview,
                      hint: 'Show the description',
                      text: conciseText(readable(signal, body), PREVIEW_CHARS),
                      facts: [...preview.facts, ...githubFacts(extra)],
                      open: link ? { to: link.to, external: link.external, label: 'Open on GitHub' } : null,
                  }
                : null
        }
        case 'conversations':
        case 'zendesk': {
            const body = bodyParagraph(signal.content, 'Issue')
            return body
                ? {
                      ...preview,
                      hint: 'Show the ticket',
                      text: conciseText(readable(signal, body), PREVIEW_CHARS),
                      facts: [...preview.facts, ...ticketFacts(extra)],
                  }
                : null
        }
        case 'analytics': {
            const rest = findingRest(signal)
            return rest
                ? {
                      ...preview,
                      hint: 'Show the finding',
                      text: conciseText(rest, PREVIEW_CHARS),
                      facts: [...preview.facts, ...anomalyFacts(extra)],
                  }
                : null
        }
    }
    return preview
}

/**
 * What an evidence row shows in place when it opens: a small piece of the source's own data, its facts,
 * and a link to the full thing. Null for a recording, which plays at once, and for a row with nothing to show but a link.
 */
export function signalPreview(signal: PreviewSignal): TodaySignalPreview | null {
    const preview = previewOf(signal)
    const empty = !preview?.code.length && !preview?.block.length && !preview?.text
    return preview && (!empty || !preview.open) ? preview : null
}
