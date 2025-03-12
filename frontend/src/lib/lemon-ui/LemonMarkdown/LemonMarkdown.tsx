import './LemonMarkdown.scss'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { cn } from 'lib/utils/css-classes'
import ReactMarkdown from 'react-markdown'

import { Link } from '../Link'

export interface LemonMarkdownProps {
    children: string
    /** Whether headings should just be <strong> text. Recommended for item descriptions. */
    lowKeyHeadings?: boolean
    /** Whether to disable the docs sidebar panel behavior and always open links in a new tab */
    disableDocsRedirect?: boolean
    className?: string
}

/** Beautifully rendered Markdown. */
export function LemonMarkdown({
    children,
    lowKeyHeadings = false,
    disableDocsRedirect = false,
    className,
}: LemonMarkdownProps): JSX.Element {
    return (
        <div className={cn('LemonMarkdown', className)}>
            {/* eslint-disable-next-line react/forbid-elements */}
            <ReactMarkdown
                renderers={{
                    link: ({ href, children }) => (
                        <Link to={href} target="_blank" targetBlankIcon disableDocsPanel={disableDocsRedirect}>
                            {children}
                        </Link>
                    ),
                    code: ({ language, value }) => (
                        <CodeSnippet language={language || Language.Text} compact>
                            {value}
                        </CodeSnippet>
                    ),
                    ...(lowKeyHeadings
                        ? {
                              heading: 'strong',
                          }
                        : {}),
                }}
                disallowedTypes={['html']} // Don't want to deal with the security considerations of HTML
            >
                {children}
            </ReactMarkdown>
        </div>
    )
}
