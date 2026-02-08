import clsx from 'clsx'
import { useState } from 'react'

export interface StepScreenshotThumbnailProps {
    mediaId: string
    onClick?: () => void
    className?: string
}

export function StepScreenshotThumbnail({
    mediaId,
    onClick,
    className,
}: StepScreenshotThumbnailProps): JSX.Element | null {
    const [hasError, setHasError] = useState(false)

    if (hasError) {
        return null
    }

    return (
        <img
            src={`/uploaded_media/${mediaId}`}
            alt="Element screenshot"
            className={clsx(className)}
            onClick={onClick}
            title="Click to view screenshot"
            onError={() => setHasError(true)}
        />
    )
}
