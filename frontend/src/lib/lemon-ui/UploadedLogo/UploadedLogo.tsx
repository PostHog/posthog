import clsx from 'clsx'
import React, { Suspense, lazy, useState } from 'react'

import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { backendAssetUrl } from 'lib/utils/apiHost'
import { retryImport } from 'lib/utils/retryImport'

import { LemonSkeleton } from '../LemonSkeleton'
import { Lettermark } from '../Lettermark'

// This file ships on every logged-in page, and quill must load only where a page turns it on.
const QuillUploadedLogo = lazy(() =>
    retryImport(() => import('./QuillUploadedLogo')).then((m) => ({ default: m.QuillUploadedLogo }))
)

export interface UploadedLogoProps {
    name: string
    /**
     * When mediaId is not provided, a lettermark is used for the logo.
     * The optional entity ID determines which lettermark color is used.
     * If a string is provided, it will be treated as a UUID (the last 4 bytes will be used as the entity ID).
     */
    entityId: number | string
    mediaId?: string | null
    /** @default 'medium' */
    size?: 'xsmall' | 'small' | 'medium' | 'xlarge'
    /** Use the outlined lettermark for signifying projects, to differentiate them from organizations. */
    outlinedLettermark?: boolean
}

export const UploadedLogo = React.forwardRef<HTMLDivElement, UploadedLogoProps>(function UploadedLogo(
    { name, mediaId, entityId, size = 'medium', outlinedLettermark },
    ref
) {
    const [isLoadingImage, setIsLoadingImage] = useState(true)
    const quillSurface = useQuillSurface()
    const imageSrc = mediaId
        ? mediaId.startsWith('data:')
            ? mediaId
            : backendAssetUrl(`/uploaded_media/${mediaId}`)
        : null

    if (quillSurface) {
        return (
            <Suspense fallback={null}>
                <QuillUploadedLogo
                    name={name}
                    entityId={entityId}
                    imageSrc={imageSrc}
                    size={size}
                    outlinedLettermark={outlinedLettermark}
                />
            </Suspense>
        )
    }

    if (!mediaId) {
        return <Lettermark index={entityId} name={name} size={size} outlined={outlinedLettermark} />
    }

    return (
        <div
            className={clsx(
                'relative flex shrink-0 overflow-hidden select-none',
                size === 'xlarge'
                    ? 'size-16 rounded before:absolute before:inset-0 before:border before:rounded'
                    : size === 'medium'
                      ? 'size-6 rounded-xs'
                      : size === 'small'
                        ? 'size-5 rounded-xs'
                        : 'size-4 rounded-xs'
            )}
            ref={ref}
        >
            {isLoadingImage && <LemonSkeleton className="absolute inset-0" />}
            <img
                className="size-full object-cover"
                src={imageSrc ?? undefined}
                alt="Uploaded logo"
                onError={() => setIsLoadingImage(false)}
                onLoad={() => setIsLoadingImage(false)}
            />
        </div>
    )
})
