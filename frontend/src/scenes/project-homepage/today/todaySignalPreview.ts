import { isNotNil, isObject } from 'lib/utils/guards'

import type { SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'

import { signalDestination, signalSlackThread } from './todayEvidence'
import { conciseText, paragraphs } from './todayProse'
import { codeSiblingFiles } from './todayQuotedCode'
import { TodayCodeFile, githubFileUrl, signalCodeFile, signalDetail, signalExtra, textOf } from './todaySignalText'

type PreviewSignal = Pick<SignalNodeApi, 'source_product' | 'source_type' | 'source_id' | 'content' | 'extra'>

interface TodayPreviewLine {
    text: string
    quiet: boolean
}

export interface TodayPreviewLink {
    to: string
    external: boolean
    label: string
}

export interface TodaySignalPreview {
    hint: string
    code: TodayCodeFile[]
    block: TodayPreviewLine[]
    text: string
    facts: string[]
    open: TodayPreviewLink | null
}

const PREVIEW_CHARS = 240
const MAX_EXCEPTIONS = 4
const FENCED_BLOCK = /```[^\n]*\n([\s\S]*?)(?:```|$)/
const FRAME_LINE = /^(\S+) in (\S+) line (\d+)$/
const IN_APP_PATH = /^(?:posthog|products|ee|common|services|frontend)\//
const SECTION_LABEL = /^\*\*([^*\n]+?):\*\*\s*/

function sentenceCase(value: string): string {
    const words = value.replace(/_/g, ' ').trim()
    return `${words.charAt(0).toUpperCase()}${words.slice(1).toLowerCase()}`
}

function readable(signal: PreviewSignal, content: string): string {
    const detail = signalDetail({ ...signal, content })
    return [detail.lead, detail.rest].filter(Boolean).join(' ')
}

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
        const shownInHeadline = index === 0 && prose.includes(exception.header)
        const title = index === 0 ? exception.header : `Caused by ${exception.header}`
        const header = shownInHeadline ? [] : [{ text: title, quiet: false }]
        return [
            ...header,
            ...(frame ? [{ text: `  ${frame.path.split('/').pop()}:${frame.line}  ${frame.fn}`, quiet: true }] : []),
        ]
    })
}

function pganalyzeQuery(signal: Pick<SignalNodeApi, 'extra'>): string | null {
    const references = signalExtra(signal).references
    if (!Array.isArray(references)) {
        return null
    }
    const query = references.find((reference) => isObject(reference) && reference.kind === 'Query')
    return isObject(query) ? textOf(query.queryText) : null
}

export function bodyParagraph(content: string, label?: string): string | null {
    const titleEnd = content.trim().indexOf('\n')
    const body = titleEnd < 0 ? [] : paragraphs(content.trim().slice(titleEnd + 1))
    const labelled = label
        ? body.find((paragraph) => paragraph.match(SECTION_LABEL)?.[1].toLowerCase() === label.toLowerCase())
        : undefined
    const chosen = labelled ?? body.find((paragraph) => !SECTION_LABEL.test(paragraph))
    return chosen ? chosen.replace(SECTION_LABEL, '').trim() || null : null
}

function githubFacts(extra: Record<string, unknown>): string[] {
    const openState = textOf(extra.state)
    const state = typeof extra.merged_at === 'string' ? 'Merged' : openState && sentenceCase(openState)
    const author = textOf(extra.author_login)
    const labels = Array.isArray(extra.labels)
        ? extra.labels.map((label) => (isObject(label) ? textOf(label.name) : textOf(label))).filter(isNotNil)
        : []
    return [state, author ? `by ${author}` : null, ...labels].filter(isNotNil)
}

const CHANNELS: Record<string, string> = { slack: 'Slack', email: 'Email', widget: 'Chat widget' }

function ticketFacts(extra: Record<string, unknown>): string[] {
    const channel = textOf(extra.channel_source)
    const priority = textOf(extra.priority)
    const status = textOf(extra.status)
    return [
        channel ? (CHANNELS[channel] ?? sentenceCase(channel)) : null,
        priority ? `${sentenceCase(priority)} priority` : null,
        status ? sentenceCase(status) : null,
    ].filter(isNotNil)
}

function anomalyFacts(extra: Record<string, unknown>): string[] {
    const verdict = textOf(extra.verdict)
    return verdict ? [sentenceCase(verdict)] : []
}

function findingRest(signal: PreviewSignal): string {
    const lead = signalDetail(signal).lead
    for (const line of signal.content.split('\n')) {
        const detail = signalDetail({ ...signal, content: line })
        if (lead && detail.lead === lead) {
            return detail.rest
        }
    }
    return ''
}

type SourcePreview = (signal: PreviewSignal, preview: TodaySignalPreview) => TodaySignalPreview | null

function scoutPreview(signal: PreviewSignal, preview: TodaySignalPreview): TodaySignalPreview {
    const codeFile = signalCodeFile(signal)
    if (codeFile) {
        return {
            ...preview,
            hint: 'Show the code',
            code: [codeFile, ...codeSiblingFiles(codeFile, signal.content)],
            facts: preview.facts.filter((fact) => fact !== codeFile.path.split('/').pop()),
            open: { to: githubFileUrl(codeFile), external: true, label: 'Open on GitHub' },
        }
    }
    const slackThread = signalSlackThread(signal)
    if (slackThread) {
        return {
            ...preview,
            hint: 'Show what the thread says',
            open: { to: slackThread, external: true, label: 'Open in Slack' },
        }
    }
    return preview
}

function stackTracePreview(signal: PreviewSignal, preview: TodaySignalPreview): TodaySignalPreview | null {
    const block = exceptionChain(signal.content)
    return block.length ? { ...preview, hint: 'Show the stack trace', block, text: '' } : null
}

function queryPreview(signal: PreviewSignal, preview: TodaySignalPreview): TodaySignalPreview | null {
    const query = pganalyzeQuery(signal)
    return query ? { ...preview, hint: 'Show the query', block: [{ text: query, quiet: false }] } : null
}

function descriptionPreview(signal: PreviewSignal, preview: TodaySignalPreview): TodaySignalPreview | null {
    const body = bodyParagraph(signal.content)
    if (!body) {
        return null
    }
    return {
        ...preview,
        hint: 'Show the description',
        text: conciseText(readable(signal, body), PREVIEW_CHARS),
        facts: [...preview.facts, ...githubFacts(signalExtra(signal))],
        open: preview.open && { ...preview.open, label: 'Open on GitHub' },
    }
}

function ticketPreview(signal: PreviewSignal, preview: TodaySignalPreview): TodaySignalPreview | null {
    const body = bodyParagraph(signal.content, 'Issue')
    if (!body) {
        return null
    }
    return {
        ...preview,
        hint: 'Show the ticket',
        text: conciseText(readable(signal, body), PREVIEW_CHARS),
        facts: [...preview.facts, ...ticketFacts(signalExtra(signal))],
    }
}

function findingPreview(signal: PreviewSignal, preview: TodaySignalPreview): TodaySignalPreview | null {
    const rest = findingRest(signal)
    if (!rest) {
        return null
    }
    return {
        ...preview,
        hint: 'Show the finding',
        text: conciseText(rest, PREVIEW_CHARS),
        facts: [...preview.facts, ...anomalyFacts(signalExtra(signal))],
    }
}

const SOURCE_PREVIEWS: Record<string, SourcePreview> = {
    signals_scout: scoutPreview,
    error_tracking: stackTracePreview,
    pganalyze: queryPreview,
    github: descriptionPreview,
    conversations: ticketPreview,
    zendesk: ticketPreview,
    analytics: findingPreview,
}

function previewOf(signal: PreviewSignal): TodaySignalPreview | null {
    const destination = signalDestination(signal)
    if (destination.kind === 'recording') {
        return null
    }
    const detail = signalDetail(signal)
    const preview: TodaySignalPreview = {
        hint: 'Read in full',
        code: [],
        block: [],
        text: detail.rest,
        facts: detail.facts,
        open:
            destination.kind === 'link'
                ? { to: destination.to, external: destination.external, label: destination.label }
                : null,
    }
    const sourcePreview = SOURCE_PREVIEWS[signal.source_product]
    return sourcePreview ? sourcePreview(signal, preview) : preview
}

export function signalPreview(signal: PreviewSignal): TodaySignalPreview | null {
    const preview = previewOf(signal)
    if (!preview) {
        return null
    }
    const hasContent = preview.code.length > 0 || preview.block.length > 0 || !!preview.text
    return hasContent || !preview.open ? preview : null
}
