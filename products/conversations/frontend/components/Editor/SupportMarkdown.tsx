import './SupportMarkdown.scss'

import clsx from 'clsx'

import { LemonMarkdown, LemonMarkdownProps } from 'lib/lemon-ui/LemonMarkdown'

export interface SupportMarkdownProps extends LemonMarkdownProps {}

/**
 * Markdown renderer for support messages.
 * Wraps LemonMarkdown with support-specific styling.
 */
export function SupportMarkdown({ className, ...props }: SupportMarkdownProps): JSX.Element {
    return <LemonMarkdown {...props} className={clsx('SupportMarkdown', className)} />
}
