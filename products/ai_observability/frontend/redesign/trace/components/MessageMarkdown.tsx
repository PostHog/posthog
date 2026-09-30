import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { cn } from 'lib/utils/css-classes'

export interface MessageMarkdownProps {
    text: string
    className?: string
}

export function MessageMarkdown({ text, className }: MessageMarkdownProps): JSX.Element {
    // Message text comes from models and end users, so it gets LemonMarkdown's untrusted-content settings.
    return (
        <LemonMarkdown
            className={cn('text-sm', className)}
            lowKeyHeadings
            disableImages
            disableMentions
            disableDocsRedirect
        >
            {text}
        </LemonMarkdown>
    )
}
