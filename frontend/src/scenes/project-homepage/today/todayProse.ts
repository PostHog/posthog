import { fromMarkdown } from 'mdast-util-from-markdown'

import { Dayjs, dayjs } from 'lib/dayjs'

const BARE_GITHUB_LINK = /(?<![(<[])https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/(?:pull|issues)\/(\d+)(?![\w/])/g

export function shortenGitHubLinks(markdown: string): string {
    return markdown.replace(BARE_GITHUB_LINK, (url, number) => `[#${number}](${url})`)
}

export function shortDate(date: string | number | Dayjs): string {
    return dayjs(date).format('D MMM')
}

const ISO_DATE = /\b(\d{4}-\d{2}-\d{2})\b/g

function readableDate(match: string): string {
    const [, month, day] = match.split('-').map(Number)
    if (month < 1 || month > 12 || day < 1 || day > 31) {
        return match
    }
    return shortDate(dayjs(`${match.slice(0, 8)}01`).add(day - 1, 'day'))
}

function readableDates(text: string): string {
    return text.replace(ISO_DATE, readableDate)
}

type TodayInlineSegment = { kind: 'text' | 'code'; text: string } | { kind: 'link'; text: string; href: string }

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

function nodeSegments(node: MarkdownNode): TodayInlineSegment[] {
    switch (node.type) {
        case 'inlineCode':
            return [{ kind: 'code', text: node.value ?? '' }]
        case 'link':
            return [{ kind: 'link', text: nodeText(node), href: node.url ?? '' }]
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
    const text = readableDates(shortenGitHubLinks(markdown).replace(/\s+/g, ' ').trim())
    const tree: MarkdownNode = fromMarkdown(text, { extensions: [INLINE_ONLY] })
    return joinedText(nodeSegments(tree)).filter((segment) => segment.text)
}

export function renderedText(markdown: string): string {
    return inlineSegments(markdown)
        .map((segment) => segment.text)
        .join('')
}
