import './LemonMarkdown.scss'

import clsx from 'clsx'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import React, { memo, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'

import { Link } from '../Link'
import { MathRenderer } from './MathRenderer'

interface LemonMarkdownContainerProps {
    children: React.ReactNode
    className?: string
}

function LemonMarkdownContainer({ children, className }: LemonMarkdownContainerProps): JSX.Element {
    return <div className={clsx('LemonMarkdown', className)}>{children}</div>
}

export interface LemonMarkdownProps {
    children: string
    /** Whether headings should just be <strong> text. Recommended for item descriptions. */
    lowKeyHeadings?: boolean
    /** Whether to disable the docs sidebar panel behavior and always open links in a new tab */
    disableDocsRedirect?: boolean
    className?: string
    wrapCode?: boolean
}

// Pre-process text to handle math expressions
function preprocessMathContent(content: string): string {
    // Replace display math ($$...$$) with a special marker
    content = content.replace(/\$\$([^$]+?)\$\$/g, (match, math) => {
        return `__DISPLAY_MATH_${btoa(math)}_DISPLAY_MATH__`
    })

    // Replace inline math ($...$) with a special marker
    content = content.replace(/\$([^$\n]+?)\$/g, (match, math) => {
        return `__INLINE_MATH_${btoa(math)}_INLINE_MATH__`
    })

    return content
}

// Custom text renderer that handles math markers
function renderTextWithMath(text: string): React.ReactNode {
    const parts: React.ReactNode[] = []
    let remaining = text
    let key = 0

    while (remaining.length > 0) {
        // Look for display math markers
        const displayMathMatch = remaining.match(/__DISPLAY_MATH_([A-Za-z0-9+/=]+)_DISPLAY_MATH__/)
        if (displayMathMatch) {
            const beforeMath = remaining.substring(0, displayMathMatch.index!)
            if (beforeMath) {
                parts.push(beforeMath)
            }

            const mathContent = atob(displayMathMatch[1])
            parts.push(
                <MathRenderer key={key++} block={true}>
                    {mathContent}
                </MathRenderer>
            )

            remaining = remaining.substring(displayMathMatch.index! + displayMathMatch[0].length)
            continue
        }

        // Look for inline math markers
        const inlineMathMatch = remaining.match(/__INLINE_MATH_([A-Za-z0-9+/=]+)_INLINE_MATH__/)
        if (inlineMathMatch) {
            const beforeMath = remaining.substring(0, inlineMathMatch.index!)
            if (beforeMath) {
                parts.push(beforeMath)
            }

            const mathContent = atob(inlineMathMatch[1])
            parts.push(
                <MathRenderer key={key++} block={false}>
                    {mathContent}
                </MathRenderer>
            )

            remaining = remaining.substring(inlineMathMatch.index! + inlineMathMatch[0].length)
            continue
        }

        // No more math markers found
        parts.push(remaining)
        break
    }

    return parts.length === 1 && typeof parts[0] === 'string' ? parts[0] : <>{parts}</>
}

const LemonMarkdownRenderer = memo(function LemonMarkdownRenderer({
    children,
    lowKeyHeadings = false,
    disableDocsRedirect = false,
    wrapCode = false,
}: LemonMarkdownProps): JSX.Element {
    const preprocessedContent = useMemo(() => preprocessMathContent(children), [children])

    const renderers = useMemo<{ [nodeType: string]: React.ElementType }>(
        () => ({
            link: ({ href, children }: any): JSX.Element => (
                <Link to={href} target="_blank" targetBlankIcon disableDocsPanel={disableDocsRedirect}>
                    {children}
                </Link>
            ),
            code: ({ language, value }: any): JSX.Element => (
                <CodeSnippet language={language || Language.Text} wrap={wrapCode} compact>
                    {value}
                </CodeSnippet>
            ),
            text: ({ value }: any): JSX.Element => <>{renderTextWithMath(value)}</>,
            ...(lowKeyHeadings
                ? {
                      heading: 'strong',
                  }
                : {}),
        }),
        [disableDocsRedirect, lowKeyHeadings, wrapCode]
    )

    return (
        /* eslint-disable-next-line react/forbid-elements */
        <ReactMarkdown
            renderers={renderers}
            disallowedTypes={['html']} // Don't want to deal with the security considerations of HTML
        >
            {preprocessedContent}
        </ReactMarkdown>
    )
})

/** Beautifully rendered Markdown. */
function LemonMarkdownComponent({
    children,
    lowKeyHeadings = false,
    disableDocsRedirect = false,
    wrapCode = false,
    className,
}: LemonMarkdownProps): JSX.Element {
    return (
        <LemonMarkdownContainer className={className}>
            <LemonMarkdownRenderer
                lowKeyHeadings={lowKeyHeadings}
                disableDocsRedirect={disableDocsRedirect}
                wrapCode={wrapCode}
            >
                {children}
            </LemonMarkdownRenderer>
        </LemonMarkdownContainer>
    )
}

export const LemonMarkdown = Object.assign(LemonMarkdownComponent, {
    Container: LemonMarkdownContainer,
    Renderer: LemonMarkdownRenderer,
})
