import './LemonMarkdown.scss'

import clsx from 'clsx'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import React, { memo, useMemo, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'

import { Link } from '../Link'

// MathJax setup (only initialised once)
import { browserAdaptor } from 'mathjax-full/js/adaptors/browserAdaptor.js'
import { RegisterHTMLHandler } from 'mathjax-full/js/handlers/html.js'
import { TeX } from 'mathjax-full/js/input/tex.js'
import { mathjax } from 'mathjax-full/js/mathjax.js'
import { SVG } from 'mathjax-full/js/output/svg.js'

let mjxDocument: any = null
function getMathJaxDocument(): any {
    if (!mjxDocument && typeof window !== 'undefined') {
        RegisterHTMLHandler(browserAdaptor())
        const tex = new TeX({
            packages: ['base', 'ams'],
            inlineMath: [['$', '$']],
            displayMath: [['$$', '$$']],
            processEscapes: true,
            processEnvironments: true,
        })
        const svg = new SVG({ fontCache: 'none' })
        mjxDocument = mathjax.document(document, { InputJax: tex, OutputJax: svg })
    }
    return mjxDocument
}

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

// --- Math helpers ---
function preprocessMath(content: string): string {
    // Display math first $$...$$
    content = content.replace(/\$\$([^$]+?)\$\$/g, (_, expr: string) => {
        return `__DISPLAY_MATH_${btoa(expr)}__`
    })

    // Inline math $...$
    content = content.replace(/\$([^$\n]+?)\$/g, (_, expr: string) => {
        return `__INLINE_MATH_${btoa(expr)}__`
    })
    return content
}

const MathSpan = ({ expr, block }: { expr: string; block: boolean }): JSX.Element => {
    const ref = useRef<HTMLSpanElement>(null)

    useEffect(() => {
        const el = ref.current
        if (!el) return
        try {
            const mjx = getMathJaxDocument()
            el.innerHTML = ''
            const node = mjx.convert(expr, { display: block })
            el.appendChild(node)
        } catch (e) {
            // fallback to plain text
            el.textContent = expr
        }
    }, [expr, block])

    return <span ref={ref} className={`math-renderer ${block ? 'math-block' : 'math-inline'}`} aria-label={expr} />
}

function renderTextWithMath(text: string): React.ReactNode {
    const pieces: React.ReactNode[] = []
    let remaining = text
    let key = 0

    const displayRegex = /__DISPLAY_MATH_([A-Za-z0-9+/=]+)__/
    const inlineRegex = /__INLINE_MATH_([A-Za-z0-9+/=]+)__/

    while (remaining.length) {
        const dMatch = remaining.match(displayRegex)
        const iMatch = remaining.match(inlineRegex)

        const firstMatch = dMatch && iMatch ? (dMatch.index! < iMatch.index! ? dMatch : iMatch) : dMatch || iMatch
        if (!firstMatch) {
            pieces.push(remaining)
            break
        }

        const index = firstMatch.index ?? 0
        if (index > 0) {
            pieces.push(remaining.slice(0, index))
        }

        const encoded = firstMatch[1]
        const expr = atob(encoded)
        const isDisplay = firstMatch[0].startsWith('__DISPLAY_MATH_')
        pieces.push(<MathSpan key={key++} expr={expr} block={isDisplay} />)

        remaining = remaining.slice(index + firstMatch[0].length)
    }

    return pieces.length === 1 ? pieces[0] : <>{pieces}</>
}

const LemonMarkdownRenderer = memo(function LemonMarkdownRenderer({
    children,
    lowKeyHeadings = false,
    disableDocsRedirect = false,
    wrapCode = false,
}: LemonMarkdownProps): JSX.Element {
    const processed = useMemo(() => preprocessMath(children), [children])

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
        <ReactMarkdown renderers={renderers} disallowedTypes={['html']}>
            {processed}
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
