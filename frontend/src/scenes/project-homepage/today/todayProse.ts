import { Dayjs, dayjs } from 'lib/dayjs'

export const SENTENCE_BREAK = /(?<=[.!?])\s+(?=[A-Z0-9"“(*`])/

const BARE_GITHUB_LINK = /(?<![(<[])https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/(?:pull|issues)\/(\d+)(?![\w/])/g

export function shortenGitHubLinks(markdown: string): string {
    return markdown.replace(BARE_GITHUB_LINK, (url, number) => `[#${number}](${url})`)
}

const LIST_MARKER = /^\s*(?:[-*+]|\d+[.)])\s+/

function balanced(text: string, marker: string): string {
    return text.split(marker).length % 2 === 0 ? `${text}${marker}` : text
}

export function conciseText(markdown: string | null | undefined, maxChars: number): string {
    const sentences = (markdown ?? '')
        .split(/\n+/)
        .map((line) => line.replace(LIST_MARKER, '').trim())
        .filter(Boolean)
        .map((line) => (/[.!?:]$/.test(line) ? line : `${line}.`))
        .flatMap((line) => line.split(SENTENCE_BREAK))
        .map((sentence) => sentence.trim())
        .filter(Boolean)
    let text = ''
    for (const sentence of sentences) {
        const next = text ? `${text} ${sentence}` : sentence
        if (text && renderedText(next).length > maxChars) {
            break
        }
        text = next
    }
    return balanced(balanced(text, '**'), '`')
}

export function plainLine(line: string): string {
    return line
        .replace(/^C:\s*/, '')
        .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
        .replace(/(?:slack (?:reply|thread|message)|thread|link):\s*https?:\/\/\S+/gi, '')
        .replace(/\s*\(\s*https?:\/\/[^\s)]+\s*\)/g, '')
        .replace(/https?:\/\/\S+/g, '')
        .replace(/`([^`]+)`/g, (_, code: string) => (/\s/.test(code) ? `“${code}”` : code))
        .replace(/[`*]/g, '')
        .replace(/\\([.#()[\]_*-])/g, '$1')
        .replace(/\s+/g, ' ')
        .replace(/\s+([.,;:])/g, '$1')
        .trim()
}

const SENTENCE_END = /[.!?](?=\s+[A-Z“"(])/g
const MIN_SENTENCE_CHARS = 40

function insideQuote(text: string): boolean {
    const opened = (text.match(/“/g) ?? []).length - (text.match(/”/g) ?? []).length
    return opened > 0 || (text.match(/"/g) ?? []).length % 2 === 1
}

export function firstSentence(text: string): string {
    for (const match of text.matchAll(SENTENCE_END)) {
        const end = (match.index ?? 0) + 1
        if (end >= MIN_SENTENCE_CHARS && !insideQuote(text.slice(0, end))) {
            return text.slice(0, end)
        }
    }
    return text
}

export function shortDate(date: string | number | Dayjs): string {
    return dayjs(date).format('D MMM')
}

const ISO_DATE = /\b(\d{4}-\d{2}-\d{2})\b/g

function readableDates(text: string): string {
    return text.replace(ISO_DATE, (match) => {
        const date = dayjs(match)
        return date.isValid() ? shortDate(date) : match
    })
}

const MONTH_DAY = /(?<=\bon )(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b/g
const BARE_INTEGER = /(?<![\w#.,/:-])(?:\d{5,7}|(?!19|20)\d{4}(?= [a-z]))(?![\w/:-]|[.,]\d)/g

export function readableExcerpt(text: string): string {
    return readableDates(text)
        .replace(
            MONTH_DAY,
            (_, month: string, day: string) =>
                `${Number(day)} ${dayjs()
                    .month(Number(month) - 1)
                    .format('MMM')}`
        )
        .replace(BARE_INTEGER, (match) => Number(match).toLocaleString('en-US'))
}

const CODE_BLOCK = /```[\s\S]*?(```|$)/g

export function withoutCodeBlocks(text: string): string {
    return text.replace(CODE_BLOCK, '\n')
}

type TodayInlineSegment = { kind: 'text' | 'code'; text: string } | { kind: 'link'; text: string; href: string }

const INLINE_MARKDOWN = /`([^`]+)`|\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)\s]+)\)/g

function joinedText(segments: TodayInlineSegment[]): TodayInlineSegment[] {
    return segments.reduce<TodayInlineSegment[]>((joined, segment) => {
        const previous = joined[joined.length - 1]
        if (previous?.kind === 'text' && segment.kind === 'text') {
            joined[joined.length - 1] = { kind: 'text', text: previous.text + segment.text }
        } else {
            joined.push(segment)
        }
        return joined
    }, [])
}

export function inlineSegments(markdown: string): TodayInlineSegment[] {
    const text = readableDates(shortenGitHubLinks(markdown).replace(/\s+/g, ' ').trim())
    const segments: TodayInlineSegment[] = []
    let last = 0
    for (const match of text.matchAll(INLINE_MARKDOWN)) {
        const index = match.index ?? 0
        segments.push({ kind: 'text', text: text.slice(last, index) })
        if (match[1] !== undefined) {
            segments.push({ kind: 'code', text: match[1] })
        } else if (match[2] !== undefined) {
            segments.push(...inlineSegments(match[2]))
        } else {
            segments.push({ kind: 'link', text: match[3], href: match[4] })
        }
        last = index + match[0].length
    }
    segments.push({ kind: 'text', text: text.slice(last) })
    return joinedText(segments).filter((segment) => segment.text)
}

export function proseSentences(markdown: string): string[] {
    return withoutCodeBlocks(markdown)
        .split('\n')
        .map(plainLine)
        .filter(Boolean)
        .flatMap((line) => line.split(SENTENCE_BREAK))
        .map((sentence) => sentence.trim())
        .filter(Boolean)
}

export function paragraphs(markdown: string): string[] {
    return markdown
        .split(/\n\s*\n/)
        .map((paragraph) => paragraph.trim())
        .filter(Boolean)
}

export function renderedText(markdown: string): string {
    return inlineSegments(markdown)
        .map((segment) => segment.text)
        .join('')
}
