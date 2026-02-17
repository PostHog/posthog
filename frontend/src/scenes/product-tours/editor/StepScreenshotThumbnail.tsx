import { useState } from 'react'

import { LemonModal } from '@posthog/lemon-ui'

export interface StepScreenshotThumbnailProps {
    mediaId: string
}

export function StepScreenshotThumbnail({ mediaId }: StepScreenshotThumbnailProps): JSX.Element | null {
    const [hasError, setHasError] = useState(false)
    const [showScreenshotModal, setShowScreenshotModal] = useState(false)

    if (hasError) {
        return null
    }

    return (
        <>
            <button
                type="button"
                className="block w-30 aspect-[4/3] overflow-hidden cursor-pointer bg-fill-tertiary border rounded transition-all hover:border-primary hover:ring-1 hover:ring-primary"
                onClick={() => setShowScreenshotModal(true)}
            >
                <img
                    src={`/uploaded_media/${mediaId}`}
                    alt="Element screenshot"
                    className="w-full h-full object-cover"
                    title="Click to view screenshot"
                    onError={() => setHasError(true)}
                />
            </button>
            <LemonModal
                isOpen={showScreenshotModal}
                onClose={() => setShowScreenshotModal(false)}
                title="Element screenshot"
                width="auto"
            >
                <div className="flex flex-col items-center justify-center gap-4">
                    <img
                        src={`/uploaded_media/${mediaId}`}
                        alt="Element screenshot"
                        className="max-w-full max-h-[70vh]"
                    />
                </div>
            </LemonModal>
        </>
    )
}
