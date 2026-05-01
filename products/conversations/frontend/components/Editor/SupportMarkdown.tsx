import './SupportMarkdown.scss'

import clsx from 'clsx'

import { LemonMarkdown, LemonMarkdownProps } from 'lib/lemon-ui/LemonMarkdown'

import { useImageLightbox } from './useImageLightbox'

export interface SupportMarkdownProps extends LemonMarkdownProps {}

/**
 * Markdown renderer for support messages.
 * Wraps LemonMarkdown with support-specific styling.
 */
export function SupportMarkdown({ className, ...props }: SupportMarkdownProps): JSX.Element {
    const { handleClick, lightbox } = useImageLightbox()

    return (
        <>
            {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions */}
            <div onClick={handleClick}>
                <LemonMarkdown {...props} className={clsx('SupportMarkdown', className)} />
            </div>
            {lightbox}
        </>
    )
}
