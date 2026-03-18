import './LemonMarkdown.scss'

import clsx from 'clsx'
import React, { memo, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { CodeSnippet, getLanguage, Language } from 'lib/components/CodeSnippet'
import { RichContentMention } from 'lib/components/RichContentEditor/RichContentNodeMention'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'

import { Link } from '../Link'
import remarkMentions from './mention'

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

const HEADING_TAGS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6'] as const

const LemonMarkdownRenderer = memo(function LemonMarkdownRenderer({
    children,
    lowKeyHeadings = false,
    disableDocsRedirect = false,
    wrapCode = false,
}: LemonMarkdownProps): JSX.Element {
    const components = useMemo(
        () => ({
            a: ({ href, children }: any): JSX.Element => (
                <Link to={href} target="_blank" targetBlankIcon disableDocsPanel={disableDocsRedirect}>
                    {children}
                </Link>
            ),
            code: ({ className, children, node, ...rest }: any): JSX.Element => {
                const languageMatch = /language-(\w+)/.exec(className || '')
                const isBlock = node?.position?.start?.line !== node?.position?.end?.line || languageMatch
                if (isBlock) {
                    const language = languageMatch ? getLanguage(languageMatch[1]) : Language.Text
                    const value = String(children).replace(/\n$/, '')
                    return (
                        <CodeSnippet language={language} wrap={wrapCode} compact>
                            {value}
                        </CodeSnippet>
                    )
                }
                return (
                    <code className={className} {...rest}>
                        {children}
                    </code>
                )
            },
            pre: ({ children }: any): JSX.Element => {
                // In v9, block code renders as <pre><code>. We handle rendering
                // in the code component, so just pass children through.
                return <>{children}</>
            },
            span: ({ className, ...props }: any): JSX.Element => {
                if (className === 'ph-mention') {
                    return <RichContentMention id={Number(props['data-mention-id'])} />
                }
                return <span className={className} {...props} />
            },
            li: ({ children, node }: any): JSX.Element => {
                const isTaskItem = node?.properties?.className?.includes('task-list-item')
                if (isTaskItem) {
                    // remark-gfm v4 renders task list items with an <input> checkbox child.
                    // We replace it with our LemonCheckbox.
                    const inputChild = node?.children?.find(
                        (child: any) => child.tagName === 'input' && child.properties?.type === 'checkbox'
                    )
                    const checked = inputChild?.properties?.checked ?? false
                    // Filter out the default checkbox input from rendered children
                    const filteredChildren = React.Children.toArray(children).filter(
                        (child: any) => !(child?.type === 'input' && child?.props?.type === 'checkbox')
                    )
                    return (
                        <li className="LemonMarkdown__task">
                            <LemonCheckbox checked={checked} disabledReason="Read-only for display" size="small" />
                            <span className="LemonMarkdown__task-content">{filteredChildren}</span>
                        </li>
                    )
                }
                return <li>{children}</li>
            },
            ...(lowKeyHeadings
                ? Object.fromEntries(
                      HEADING_TAGS.map((tag) => [
                          tag,
                          ({ children }: any): JSX.Element => (
                              <strong className="LemonMarkdown__low-key-heading">{children}</strong>
                          ),
                      ])
                  )
                : {}),
        }),
        [disableDocsRedirect, lowKeyHeadings, wrapCode]
    )

    return (
        /* eslint-disable-next-line react/forbid-elements */
        <ReactMarkdown components={components} remarkPlugins={[remarkGfm, remarkMentions]} skipHtml>
            {children}
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
