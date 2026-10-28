import { fromMarkdown } from 'mdast-util-from-markdown'

import { Dayjs, dayjs } from 'lib/dayjs'

const BARE_GITHUB_LINK = /(?<![(<[])https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/(?:pull|issues)\/(\d+)(?![\w/])/g

export function shortDate(date: string | number | Dayjs): string {
    return dayjs(date).format('D MMM')
}

const ISO_DATE = /\b(\d{4}-\d{2}-\d{2})\b/g

function readableDate(match: string): string {
    const [year, month, day] = match.split('-').map(Number)
    const date = new Date(Date.UTC(year, month - 1, day))
    const exists = year >= 1 && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
    return exists ? shortDate(dayjs(match)) : match
}

function readableDates(text: string): string {
    return text.replace(ISO_DATE, readableDate)
}

export type TodayInlineSegment = { kind: 'text' | 'code'; text: string } | { kind: 'link'; text: string; href: string }

interface MarkdownNode {
    type: string
    value?: string
    url?: string
    alt?: string | null
    children?: MarkdownNode[]
}

const INLINE_ONLY = {
    disable: {
        null: [
            'blockQuote',
            'codeFenced',
            'codeIndented',
            'definition',
            'headingAtx',
            'htmlFlow',
            'list',
            'setextUnderline',
            'thematicBreak',
        ],
    },
}

function nodeText(node: MarkdownNode): string {
    return node.value ?? node.alt ?? (node.children ?? []).map(nodeText).join('')
}

function proseSegments(text: string): TodayInlineSegment[] {
    const segments: TodayInlineSegment[] = []
    let last = 0
    for (const match of text.matchAll(BARE_GITHUB_LINK)) {
        segments.push({ kind: 'text', text: readableDates(text.slice(last, match.index)) })
        segments.push({ kind: 'link', text: `#${match[1]}`, href: match[0] })
        last = match.index + match[0].length
    }
    segments.push({ kind: 'text', text: readableDates(text.slice(last)) })
    return segments
}

function labelText(node: MarkdownNode): string {
    if (node.type === 'text') {
        return readableDates(node.value ?? '')
    }
    return node.children ? node.children.map(labelText).join('') : nodeText(node)
}

function nodeSegments(node: MarkdownNode): TodayInlineSegment[] {
    switch (node.type) {
        case 'text':
            return proseSegments(node.value ?? '')
        case 'inlineCode':
            return [{ kind: 'code', text: node.value ?? '' }]
        case 'link':
            return [{ kind: 'link', text: labelText(node), href: node.url ?? '' }]
        case 'break':
            return [{ kind: 'text', text: ' ' }]
        default:
            return node.children ? node.children.flatMap(nodeSegments) : [{ kind: 'text', text: nodeText(node) }]
    }
}

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
    const tree: MarkdownNode = fromMarkdown(markdown.replace(/\s+/g, ' ').trim(), { extensions: [INLINE_ONLY] })
    return joinedText(nodeSegments(tree)).filter((segment) => segment.text)
}

export function renderedText(markdown: string): string {
    return inlineSegments(markdown)
        .map((segment) => segment.text)
        .join('')
}
