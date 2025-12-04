import { JSONContent } from 'lib/components/RichContentEditor/types'

interface MarkdownToken {
    type: string
    content?: string
    level?: number
    language?: string | null
    items?: string[]
    start?: number
}

/**
 * Simple markdown tokenizer that handles block-level elements.
 */
function tokenizeMarkdown(text: string): MarkdownToken[] {
    const tokens: MarkdownToken[] = []
    const lines = text.split('\n')
    let i = 0

    while (i < lines.length) {
        const line = lines[i]

        // Empty line
        if (line.trim() === '') {
            i++
            continue
        }

        // Heading
        const headingMatch = line.match(/^(#{1,6})\s+(.+)$/)
        if (headingMatch) {
            tokens.push({
                type: 'heading',
                level: headingMatch[1].length,
                content: headingMatch[2].trim(),
            })
            i++
            continue
        }

        // Code block
        const codeMatch = line.match(/^```(\w*)\s*$/)
        if (codeMatch) {
            const language = codeMatch[1] || null
            const codeLines: string[] = []
            i++
            while (i < lines.length && lines[i].trim() !== '```') {
                codeLines.push(lines[i])
                i++
            }
            tokens.push({
                type: 'code_block',
                language,
                content: codeLines.join('\n'),
            })
            i++ // Skip closing ```
            continue
        }

        // Blockquote
        const blockquoteMatch = line.match(/^>\s*(.*)$/)
        if (blockquoteMatch) {
            const quoteLines: string[] = []
            while (i < lines.length) {
                const qMatch = lines[i].match(/^>\s*(.*)$/)
                if (qMatch) {
                    quoteLines.push(qMatch[1])
                    i++
                } else {
                    break
                }
            }
            tokens.push({
                type: 'blockquote',
                content: quoteLines.join('\n'),
            })
            continue
        }

        // Horizontal rule
        if (/^(-{3,}|\*{3,}|_{3,})$/.test(line.trim())) {
            tokens.push({ type: 'horizontal_rule' })
            i++
            continue
        }

        // Unordered list
        const ulMatch = line.match(/^(\s*)([-*+])\s+(.+)$/)
        if (ulMatch) {
            const items: string[] = []
            const baseIndent = ulMatch[1]
            while (i < lines.length) {
                const itemMatch = lines[i].match(
                    new RegExp(`^${baseIndent.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}[-*+]\\s+(.+)$`)
                )
                if (itemMatch) {
                    items.push(itemMatch[1])
                    i++
                } else {
                    break
                }
            }
            tokens.push({ type: 'unordered_list', items })
            continue
        }

        // Ordered list
        const olMatch = line.match(/^(\s*)(\d+)\.\s+(.+)$/)
        if (olMatch) {
            const items: string[] = []
            const baseIndent = olMatch[1]
            const start = parseInt(olMatch[2], 10)
            while (i < lines.length) {
                const itemMatch = lines[i].match(
                    new RegExp(`^${baseIndent.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\d+\\.\\s+(.+)$`)
                )
                if (itemMatch) {
                    items.push(itemMatch[1])
                    i++
                } else {
                    break
                }
            }
            tokens.push({ type: 'ordered_list', items, start })
            continue
        }

        // Paragraph - collect lines until we hit a blank line or block element
        const paraLines: string[] = []
        while (i < lines.length) {
            const pLine = lines[i]
            if (pLine.trim() === '') {
                break
            }
            if (
                /^#{1,6}\s+/.test(pLine) ||
                pLine.startsWith('```') ||
                /^>\s*/.test(pLine) ||
                /^(-{3,}|\*{3,}|_{3,})$/.test(pLine.trim()) ||
                /^(\s*)([-*+]|\d+\.)\s+/.test(pLine)
            ) {
                break
            }
            paraLines.push(pLine)
            i++
        }
        if (paraLines.length > 0) {
            tokens.push({
                type: 'paragraph',
                content: paraLines.join(' ').trim(),
            })
        }
    }

    return tokens
}

interface Mark {
    type: string
    attrs?: Record<string, any>
}

interface InlineContent {
    type: 'text'
    text: string
    marks?: Mark[]
}

/**
 * Parse inline markdown formatting (bold, italic, code, links).
 */
function parseInlineContent(text: string): InlineContent[] {
    if (!text) {
        return []
    }

    const content: InlineContent[] = []
    let pos = 0

    // Patterns in order of priority
    const patterns: Array<{ regex: RegExp; type: string }> = [
        { regex: /\*\*(.+?)\*\*/, type: 'bold' },
        { regex: /__(.+?)__/, type: 'bold' },
        { regex: /\*(.+?)\*/, type: 'italic' },
        { regex: /_(.+?)_/, type: 'italic' },
        { regex: /`(.+?)`/, type: 'code' },
        { regex: /~~(.+?)~~/, type: 'strike' },
        { regex: /\[([^\]]*)\]\(([^)]*)\)/, type: 'link' },
    ]

    while (pos < text.length) {
        let earliestMatch: { start: number; end: number; type: string; data: any } | null = null

        for (const pattern of patterns) {
            const match = pattern.regex.exec(text.slice(pos))
            if (match) {
                const matchStart = pos + match.index
                if (!earliestMatch || matchStart < earliestMatch.start) {
                    earliestMatch = {
                        start: matchStart,
                        end: matchStart + match[0].length,
                        type: pattern.type,
                        data: pattern.type === 'link' ? { text: match[1], href: match[2] } : { text: match[1] },
                    }
                }
            }
        }

        if (!earliestMatch) {
            // No more patterns, add remaining text
            const remaining = text.slice(pos)
            if (remaining) {
                content.push({ type: 'text', text: remaining })
            }
            break
        }

        // Add text before the match
        if (earliestMatch.start > pos) {
            content.push({ type: 'text', text: text.slice(pos, earliestMatch.start) })
        }

        // Add the formatted content
        const { type, data } = earliestMatch
        if (type === 'link') {
            content.push({
                type: 'text',
                text: data.text,
                marks: [{ type: 'link', attrs: { href: data.href, target: '_blank' } }],
            })
        } else if (data.text) {
            content.push({
                type: 'text',
                text: data.text,
                marks: [{ type }],
            })
        }

        pos = earliestMatch.end
    }

    return content.filter((c) => c.text)
}

/**
 * Convert markdown tokens to tiptap JSONContent.
 */
function convertTokenToContent(token: MarkdownToken): JSONContent[] {
    switch (token.type) {
        case 'paragraph': {
            const content = parseInlineContent(token.content || '')
            return [
                {
                    type: 'paragraph',
                    content: content.length > 0 ? content : [{ type: 'text', text: ' ' }],
                },
            ]
        }

        case 'heading': {
            const content = parseInlineContent(token.content || '')
            return [
                {
                    type: 'heading',
                    attrs: { level: token.level },
                    content: content.length > 0 ? content : [{ type: 'text', text: ' ' }],
                },
            ]
        }

        case 'code_block':
            return [
                {
                    type: 'codeBlock',
                    attrs: token.language ? { language: token.language } : {},
                    content: [{ type: 'text', text: token.content || '' }],
                },
            ]

        case 'blockquote': {
            // Recursively parse blockquote content
            const innerTokens = tokenizeMarkdown(token.content || '')
            const innerContent = innerTokens.flatMap(convertTokenToContent)
            return [
                {
                    type: 'blockquote',
                    content:
                        innerContent.length > 0
                            ? innerContent
                            : [{ type: 'paragraph', content: [{ type: 'text', text: ' ' }] }],
                },
            ]
        }

        case 'horizontal_rule':
            return [{ type: 'horizontalRule' }]

        case 'unordered_list': {
            const items = (token.items || []).map((item) => ({
                type: 'listItem',
                content: [
                    {
                        type: 'paragraph',
                        content: parseInlineContent(item),
                    },
                ],
            }))
            return [{ type: 'bulletList', content: items }]
        }

        case 'ordered_list': {
            const items = (token.items || []).map((item) => ({
                type: 'listItem',
                content: [
                    {
                        type: 'paragraph',
                        content: parseInlineContent(item),
                    },
                ],
            }))
            return [
                {
                    type: 'orderedList',
                    attrs: { start: token.start || 1 },
                    content: items,
                },
            ]
        }

        default:
            return []
    }
}

/**
 * Convert markdown string to tiptap JSONContent array.
 */
export function markdownToTiptap(markdown: string): JSONContent[] {
    const tokens = tokenizeMarkdown(markdown)
    return tokens.flatMap(convertTokenToContent)
}
