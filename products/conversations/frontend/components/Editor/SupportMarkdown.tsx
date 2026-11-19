import './SupportMarkdown.scss'

import clsx from 'clsx'

import { LemonMarkdown, LemonMarkdownProps } from 'lib/lemon-ui/LemonMarkdown'

export interface SupportMarkdownProps extends LemonMarkdownProps {}

// Screenshots in tickets are often too detailed to read at message width, and a new tab lets the reader
// zoom with the browser
function openImageInNewTab(e: React.MouseEvent): void {
    const target = e.target as HTMLElement
    if (target instanceof HTMLImageElement) {
        window.open(target.src, '_blank', 'noopener,noreferrer')
    }
}

/**
 * Markdown renderer for support messages.
 * Wraps LemonMarkdown with support-specific styling.
 * Message text is plain text a person typed, so tag-like text such as `<example>` shows as typed.
 */
export function SupportMarkdown({
    className,
    wrapCode = true,
    literalHtml = true,
    ...props
}: SupportMarkdownProps): JSX.Element {
    return (
        // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions
        <div onClick={openImageInNewTab}>
            <LemonMarkdown
                {...props}
                wrapCode={wrapCode}
                literalHtml={literalHtml}
                className={clsx('SupportMarkdown', className)}
            />
        </div>
    )
}
