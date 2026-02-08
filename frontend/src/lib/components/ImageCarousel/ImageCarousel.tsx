import { useEffect, useState } from 'react'

import { IconChevronLeft, IconChevronRight, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

interface ImageCarouselProps {
    imageUrls: string[]
    loading?: boolean
    onDelete?: (url: string) => void
}

export function ImageCarousel({ imageUrls, loading, onDelete }: ImageCarouselProps): JSX.Element {
    const [currentIndex, setCurrentIndex] = useState(0)

    // Reset index if it goes out of bounds (e.g. after deletion)
    useEffect(() => {
        if (currentIndex >= imageUrls.length && imageUrls.length > 0) {
            setCurrentIndex(imageUrls.length - 1)
        }
    }, [imageUrls.length, currentIndex])

    if (loading || imageUrls.length === 0) {
        return <></>
    }

    const showArrows = imageUrls.length > 1
    const currentImageUrl = imageUrls[currentIndex]

    const goToPrevious = (): void => {
        setCurrentIndex((prev) => (prev === 0 ? imageUrls.length - 1 : prev - 1))
    }

    const goToNext = (): void => {
        setCurrentIndex((prev) => (prev === imageUrls.length - 1 ? 0 : prev + 1))
    }

    return (
        <div className="relative group border rounded bg-bg-light w-full max-w-[600px] aspect-[3/2] flex items-center justify-center overflow-hidden">
            <img src={currentImageUrl} className="max-w-[96%] max-h-[96%] object-contain" />

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
                    className="absolute top-[2%] right-[2%] bg-surface-primary/80 opacity-0 group-hover:opacity-100 transition-opacity shadow-md z-10"
                />
            )}

            {showArrows && (
                <>
                    <LemonButton
                        icon={<IconChevronLeft />}
                        size="small"
                        type="secondary"
                        onClick={goToPrevious}
                        className="absolute top-1/2 left-[2%] -translate-y-1/2 bg-surface-primary/80 opacity-0 group-hover:opacity-100 transition-opacity shadow-md z-10"
                    />
                    <LemonButton
                        icon={<IconChevronRight />}
                        size="small"
                        type="secondary"
                        onClick={goToNext}
                        className="absolute top-1/2 right-[2%] -translate-y-1/2 bg-surface-primary/80 opacity-0 group-hover:opacity-100 transition-opacity shadow-md z-10"
                    />
                    <div className="absolute bottom-[2%] left-1/2 -translate-x-1/2 bg-surface-primary/80 px-2 py-1 rounded-full text-xs font-semibold shadow-sm opacity-0 group-hover:opacity-100 transition-opacity z-10">
                        {currentIndex + 1} / {imageUrls.length}
                    </div>
                </>
            )}
        </div>
    )
}
