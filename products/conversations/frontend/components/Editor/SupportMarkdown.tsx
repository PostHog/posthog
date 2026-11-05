import './SupportMarkdown.scss'

import clsx from 'clsx'
import { useMemo } from 'react'

import { escapeRawHtmlTags } from 'lib/components/AgentObjectTags/rewriteAgentObjectTags'
import { LemonMarkdown, LemonMarkdownProps } from 'lib/lemon-ui/LemonMarkdown'

import { useImageLightbox } from './useImageLightbox'

export interface SupportMarkdownProps extends LemonMarkdownProps {}

/**
 * Markdown renderer for support messages.
 * Wraps LemonMarkdown with support-specific styling.
 */
export function SupportMarkdown({ className, wrapCode = true, children, ...props }: SupportMarkdownProps): JSX.Element {
    const { handleClick, lightbox } = useImageLightbox()
    // Message text is plain text a person typed. LemonMarkdown drops raw HTML, so tag-like text
    // such as `<example>` would vanish from the message unless it is escaped first.
    const content = useMemo(() => escapeRawHtmlTags(children), [children])

    return (
        <>
            {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions */}
            <div onClick={handleClick}>
                <LemonMarkdown {...props} wrapCode={wrapCode} className={clsx('SupportMarkdown', className)}>
                    {content}
                </LemonMarkdown>
            </div>
            {lightbox}
        </>
    )
}
