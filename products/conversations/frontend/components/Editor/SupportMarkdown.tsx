import './SupportMarkdown.scss'

import clsx from 'clsx'
import { useCallback, useState } from 'react'

import { LemonMarkdown, LemonMarkdownProps } from 'lib/lemon-ui/LemonMarkdown'

import { ImageLightbox } from './ImageLightbox'

export interface SupportMarkdownProps extends LemonMarkdownProps {}

/**
 * Markdown renderer for support messages.
 * Wraps LemonMarkdown with support-specific styling.
 */
export function SupportMarkdown({ className, ...props }: SupportMarkdownProps): JSX.Element {
    const [lightboxSrc, setLightboxSrc] = useState<string | null>(null)

    const handleClick = useCallback((e: React.MouseEvent) => {
        const target = e.target as HTMLElement
        if (target.tagName === 'IMG') {
            setLightboxSrc((target as HTMLImageElement).src)
        }
    }, [])

    return (
        <>
            {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions */}
            <div onClick={handleClick}>
                <LemonMarkdown {...props} className={clsx('SupportMarkdown', className)} />
            </div>
            {lightboxSrc && <ImageLightbox src={lightboxSrc} onClose={() => setLightboxSrc(null)} />}
        </>
    )
}
