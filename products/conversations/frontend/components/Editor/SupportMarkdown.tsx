import './SupportMarkdown.scss'

import clsx from 'clsx'
import React, { useState } from 'react'

import { IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMarkdown, LemonMarkdownProps } from 'lib/lemon-ui/LemonMarkdown'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

/**
 * Validates that a URL is safe to render (http, https, or data URLs only)
 * Prevents javascript: and other potentially dangerous URL schemes
 */
function isSafeImageUrl(url: string): boolean {
    if (!url) {
        return false
    }
    try {
        const parsed = new URL(url, window.location.origin)
        return ['http:', 'https:', 'data:'].includes(parsed.protocol)
    } catch {
        // Relative URLs are safe
        return !url.includes(':') || url.startsWith('/')
    }
}

function ImageWithLightbox({ src, alt }: { src: string; alt?: string }): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const [isLoading, setIsLoading] = useState(true)
    const [hasError, setHasError] = useState(false)

    // Reset state when src changes (e.g., if component is reused with different image)
    React.useEffect(() => {
        setIsLoading(true)
        setHasError(false)
    }, [src])

    // Validate URL is safe before rendering
    if (!isSafeImageUrl(src)) {
        return (
            <span className="SupportMarkdown__image-error text-muted-alt text-xs italic">
                Invalid image URL{alt ? `: ${alt}` : ''}
            </span>
        )
    }

    if (hasError) {
        return (
            <span className="SupportMarkdown__image-error text-muted-alt text-xs italic">
                Failed to load image{alt ? `: ${alt}` : ''}
            </span>
        )
    }

    return (
        <>
            <span className="SupportMarkdown__image-wrapper">
                {isLoading && <LemonSkeleton className="SupportMarkdown__image-skeleton" />}
                <img
                    src={src}
                    alt={alt || 'Image'}
                    className={clsx('SupportMarkdown__image', isLoading && 'invisible')}
                    onClick={() => setIsOpen(true)}
                    onLoad={() => setIsLoading(false)}
                    onError={() => {
                        setIsLoading(false)
                        setHasError(true)
                    }}
                    loading="lazy"
                />
            </span>
            <LemonModal isOpen={isOpen} onClose={() => setIsOpen(false)} simple>
                <div className="relative">
                    <LemonButton
                        icon={<IconX />}
                        size="small"
                        onClick={() => setIsOpen(false)}
                        className="absolute top-2 right-2 z-10 bg-surface-primary"
                    />
                    <img src={src} alt={alt || 'Image'} className="max-w-[90vw] max-h-[90vh] rounded" />
                </div>
            </LemonModal>
        </>
    )
}

export interface SupportMarkdownProps extends LemonMarkdownProps {}

/**
 * Markdown renderer for support messages with image lightbox support.
 * Wraps LemonMarkdown with custom image renderer.
 */
export function SupportMarkdown({ className, ...props }: SupportMarkdownProps): JSX.Element {
    return (
        <LemonMarkdown
            {...props}
            className={clsx('SupportMarkdown', className)}
            customRenderers={{
                image: ({ src, alt }: { src: string; alt?: string }) => <ImageWithLightbox src={src} alt={alt} />,
            }}
        />
    )
}
