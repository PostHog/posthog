import './LemonMarkdown.scss'

import clsx from 'clsx'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import React, { memo, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import { useValues } from 'kea'
import { membersLogic } from 'scenes/organization/membersLogic'

import { Link } from '../Link'
import { MarkdownMention } from './MarkdownMention'

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
    // We need access to members to validate mentions
    const { meFirstMembers } = useValues(membersLogic)

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
            text: ({ value }: any): JSX.Element => {
                // Split text by @ to get potential mentions
                const parts = value.split(/(@)/g)
                const result: React.ReactNode[] = []

                for (let i = 0; i < parts.length; i++) {
                    const part = parts[i]

                    if (part === '@' && i + 1 < parts.length) {
                        // This is a potential mention start
                        const afterAt = parts[i + 1]

                        // Find the longest matching username from the start of afterAt
                        let bestMatch = ''
                        let bestMatchMember = null

                        for (const member of meFirstMembers) {
                            const firstName = member.user.first_name

                            // Check if afterAt starts with this member's first name
                            if (afterAt.toLowerCase().startsWith(firstName.toLowerCase())) {
                                if (firstName.length > bestMatch.length) {
                                    bestMatch = firstName
                                    bestMatchMember = member
                                }
                            }
                        }

                        if (bestMatch) {
                            // Found a valid mention
                            result.push(
                                <MarkdownMention key={i} displayName={bestMatch} userId={bestMatchMember?.user.id} />
                            )

                            // Add the remaining text after the mention
                            const remainingText = afterAt.slice(bestMatch.length)
                            if (remainingText) {
                                result.push(remainingText)
                            }

                            // Skip the next part since we've processed it
                            i++
                        } else {
                            // Not a valid mention, just add @ and continue
                            result.push('@')
                        }
                    } else if (part && part !== '@') {
                        // Regular text
                        result.push(part)
                    }
                }

                return <>{result}</>
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
