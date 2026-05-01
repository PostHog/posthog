import { useEffect } from 'react'
import { createPortal } from 'react-dom'

import { cn } from 'lib/utils/css-classes'

export interface ImageLightboxProps {
    src: string
    alt?: string
    onClose: () => void
}

export function ImageLightbox({ src, alt, onClose }: ImageLightboxProps): JSX.Element {
    useEffect(() => {
        const handleKey = (e: KeyboardEvent): void => {
            if (e.key === 'Escape') {
                onClose()
            }
        }
        document.addEventListener('keydown', handleKey)
        return () => document.removeEventListener('keydown', handleKey)
    }, [onClose])

    return createPortal(
        <div
            className={cn(
                'fixed inset-0 flex items-center justify-center',
                'bg-overlay animate-in fade-in duration-150 cursor-zoom-out'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ zIndex: 'var(--z-force-modal-above-popovers)' }}
            onClick={onClose}
        >
            <img
                src={src}
                alt={alt || 'Image preview'}
                className="max-w-[90vw] max-h-[90vh] object-contain rounded-lg shadow-xl cursor-zoom-out"
            />
        </div>,
        document.body
    )
}
