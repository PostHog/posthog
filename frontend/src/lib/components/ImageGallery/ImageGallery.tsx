import { useEffect, useState } from 'react'

import { IconChevronLeft, IconChevronRight, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

interface ImageGalleryProps {
    imageUrls: string[]
    onDelete?: (url: string) => void
}

export function ImageGallery({ imageUrls, onDelete }: ImageGalleryProps): JSX.Element {
    const [currentIndex, setCurrentIndex] = useState(0)

    // Reset index if it goes out of bounds (e.g. after deletion)
    useEffect(() => {
        if (currentIndex >= imageUrls.length && imageUrls.length > 0) {
            setCurrentIndex(imageUrls.length - 1)
        }
    }, [imageUrls.length, currentIndex])

    if (!imageUrls || imageUrls.length === 0) {
        return <></>
    }

    const showArrows = imageUrls.length > 1
    const currentImageUrl = imageUrls[currentIndex]

    const handlePrevious = (): void => {
        setCurrentIndex((prev) => (prev === 0 ? imageUrls.length - 1 : prev - 1))
    }

    const handleNext = (): void => {
        setCurrentIndex((prev) => (prev === imageUrls.length - 1 ? 0 : prev + 1))
    }

    return (
        <div className="relative group border rounded p-2 bg-bg-light w-full max-w-[600px] aspect-[3/2] flex items-center justify-center overflow-hidden">
            <img src={currentImageUrl} className="max-w-full max-h-full object-contain" />

            {onDelete && (
                <LemonButton
                    icon={<IconTrash />}
                    type="secondary"
                    status="danger"
                    size="small"
                    onClick={() =>
                        LemonDialog.open({
                            title: 'Delete image',
                            description: 'Are you sure you want to delete this image?',
                            primaryButton: {
                                children: 'Delete',
                                status: 'danger',
                                onClick: () => onDelete(currentImageUrl),
                            },
                            secondaryButton: {
                                children: 'Cancel',
                            },
                        })
                    }
                    tooltip="Delete image"
                    className="absolute top-4 right-4 bg-surface-primary/80 opacity-0 group-hover:opacity-100 transition-opacity shadow-md z-10"
                />
            )}

            {showArrows && (
                <>
                    <LemonButton
                        icon={<IconChevronLeft />}
                        size="medium"
                        type="secondary"
                        onClick={handlePrevious}
                        className="absolute top-1/2 left-4 -translate-y-1/2 bg-surface-primary/80 opacity-0 group-hover:opacity-100 transition-opacity shadow-md z-10"
                    />
                    <LemonButton
                        icon={<IconChevronRight />}
                        size="medium"
                        type="secondary"
                        onClick={handleNext}
                        className="absolute top-1/2 right-4 -translate-y-1/2 bg-surface-primary/80 opacity-0 group-hover:opacity-100 transition-opacity shadow-md z-10"
                    />
                    <div className="absolute bottom-4 left-1/2 -translate-x-1/2 bg-surface-primary/80 px-2 py-1 rounded-full text-xs font-semibold shadow-sm opacity-0 group-hover:opacity-100 transition-opacity z-10">
                        {currentIndex + 1} / {imageUrls.length}
                    </div>
                </>
            )}
        </div>
    )
}
