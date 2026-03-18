import { marked } from 'marked'

type Token = ReturnType<typeof marked.lexer>[number]

function resolveUrl(href: string): string {
    if (!href) {
        return href
    }
    // Already absolute
    if (href.startsWith('http://') || href.startsWith('https://')) {
        return href
    }
    // Relative URL - prefix with current origin
    if (typeof window !== 'undefined') {
        return new URL(href, window.location.origin).href
    }
    return href
}

/**
 * Converts markdown text to plain text by removing all markdown formatting
 */
export function stripMarkdown(markdown: string): string {
    // Parse markdown to tokens
    const tokens = marked.lexer(markdown)

    // Extract text from tokens recursively
    const extractText = (token: Token): string => {
        switch (token.type) {
            case 'paragraph':
                return 'tokens' in token && Array.isArray(token.tokens)
                    ? token.tokens.map(extractText).join('')
                    : 'text' in token
                      ? String(token.text)
                      : ''

            case 'text':
                return 'tokens' in token && Array.isArray(token.tokens)
                    ? token.tokens.map(extractText).join('')
                    : 'text' in token
                      ? String(token.text)
                      : ''

            case 'heading':
                return token.tokens ? token.tokens.map(extractText).join('') : ''

            case 'list':
                return token.items
                    .map((item: any, index: number) => {
                        const prefix = token.ordered ? `${(token.start || 1) + index}. ` : '- '
                        return prefix + item.tokens.map(extractText).join('')
                    })
                    .join('\n')

            case 'list_item':
                return token.tokens ? token.tokens.map(extractText).join('') : ''

            case 'blockquote':
                return token.tokens ? token.tokens.map(extractText).join('') : ''

            case 'code':
                return token.text

            case 'codespan':
                return token.text

            case 'strong':
            case 'em':
            case 'del':
                return token.tokens ? token.tokens.map(extractText).join('') : ''

            case 'link': {
                const linkText = token.tokens ? token.tokens.map(extractText).join('') : token.text || ''
                const href = resolveUrl(token.href)
                return linkText && href ? `${linkText} (${href})` : linkText || href || ''
            }

            case 'image':
                return token.tokens ? token.tokens.map(extractText).join('') : token.text || ''

            case 'br':
                return '\n'

            case 'space':
                return ''

            case 'hr':
                return '---'

            case 'html':
                return ''

            case 'table':
                // Extract text from table rows and cells
                const headerText = token.header.map((cell: any) => cell.tokens.map(extractText).join('')).join(' | ')
                const rowsText = token.rows
                    .map((row: any) => row.map((cell: any) => cell.tokens.map(extractText).join('')).join(' | '))
                    .join('\n')
                return headerText + '\n' + rowsText

            default:
                // For any unhandled token types, try to extract text if available
                if ('text' in token && typeof token.text === 'string') {
                    return token.text
                }
                if ('tokens' in token && Array.isArray(token.tokens)) {
                    return token.tokens.map(extractText).join('')
                }
                return ''
        }
    }

    // Extract text from all tokens and join with double newlines between blocks
    const result = tokens.map(extractText).join('\n\n')

    // Replace multiple consecutive newlines (3+) with just 2 to preserve paragraph breaks
    return result.replace(/\n{3,}/g, '\n\n').trim()
}
