import ReactMarkdown from 'react-markdown'
import './LemonMarkdown.scss'
import { Link } from '../Link'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import clsx from 'clsx'

export interface LemonMarkdownProps {
    children: string
    /** Whether headings should just be <strong> text. Recommended for item descriptions. */
    lowKeyHeadings?: boolean
    className?: string
}

/** Beautifully rendered Markdown. */
export function LemonMarkdown({ children, lowKeyHeadings = false, className }: LemonMarkdownProps): JSX.Element {
    return (
        <div className={clsx('LemonMarkdown', className)}>
            {/* eslint-disable-next-line react/forbid-elements */}
            <ReactMarkdown
                renderers={{
                    link: ({ href, children }) => (
                        <Link to={href} target="_blank" targetBlankIcon>
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
