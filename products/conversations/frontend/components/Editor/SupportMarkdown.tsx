import './SupportMarkdown.scss'

import clsx from 'clsx'

import { LemonMarkdown, LemonMarkdownProps } from 'lib/lemon-ui/LemonMarkdown'

import { useImageLightbox } from './useImageLightbox'

export interface SupportMarkdownProps extends LemonMarkdownProps {}

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
    const { handleClick, lightbox } = useImageLightbox()

    return (
        <>
            {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions */}
            <div onClick={handleClick}>
                <LemonMarkdown
                    {...props}
                    wrapCode={wrapCode}
                    literalHtml={literalHtml}
                    className={clsx('SupportMarkdown', className)}
                />
            </div>
            {lightbox}
        </>
    )
}
