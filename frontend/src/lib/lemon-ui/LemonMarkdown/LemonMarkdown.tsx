import './LemonMarkdown.scss'

import clsx from 'clsx'
import { props } from 'kea'
import React, { memo, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { RichContentMention } from 'lib/components/RichContentEditor/RichContentNodeMention'
import { RichContentNodeType } from 'lib/components/RichContentEditor/types'
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

const LemonMarkdownRenderer = memo(function LemonMarkdownRenderer({
    children,
    lowKeyHeadings = false,
    disableDocsRedirect = false,
    wrapCode = false,
}: LemonMarkdownProps): JSX.Element {
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
            [RichContentNodeType.Mention]: ({ id }): JSX.Element => <RichContentMention id={id} />,
            listItem: ({ checked, children }: any): JSX.Element => {
                // Handle task list items with LemonCheckbox
                if (checked != null) {
                    return (
                        <li className="LemonMarkdown__task">
                            <LemonCheckbox checked={checked} disabledReason="Read-only for display" size="small" />
                            <span className="LemonMarkdown__task-content">{children}</span>
                        </li>
                    )
                }
                // Regular list item
                return <li {...props}>{children}</li>
            },
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
            plugins={[remarkGfm, remarkMentions]}
        >
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
