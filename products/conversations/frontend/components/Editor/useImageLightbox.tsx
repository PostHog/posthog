import { useCallback, useState } from 'react'

import { ImageLightbox } from './ImageLightbox'

export function useImageLightbox(filter?: (el: HTMLImageElement) => boolean): {
    handleClick: (e: React.MouseEvent) => void
    lightbox: JSX.Element | null
} {
    const [lightboxSrc, setLightboxSrc] = useState<string | null>(null)

    const handleClick = useCallback(
        (e: React.MouseEvent) => {
            const target = e.target as HTMLElement
            if (target.tagName === 'IMG' && (!filter || filter(target as HTMLImageElement))) {
                setLightboxSrc((target as HTMLImageElement).src)
            }
        },
        [filter]
    )

    const lightbox = lightboxSrc ? <ImageLightbox src={lightboxSrc} onClose={() => setLightboxSrc(null)} /> : null

    return { handleClick, lightbox }
}
