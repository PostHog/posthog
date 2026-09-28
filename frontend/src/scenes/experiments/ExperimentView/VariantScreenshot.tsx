import { useActions, useValues } from 'kea'
import { ReactNode, useCallback, useEffect, useRef, useState } from 'react'

import { IconChevronLeft, IconChevronRight, IconX } from '@posthog/icons'
import {
    LemonButton,
    LemonDivider,
    LemonFileInput,
    LemonModal,
    LemonSkeleton,
    lemonToast,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { ZoomableImage } from 'lib/components/ZoomableImage/ZoomableImage'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { backendAssetUrl } from 'lib/utils/apiHost'

import { experimentLogic } from '../experimentLogic'
import { VariantTag } from './VariantTag'

export function VariantScreenshot({
    variantKey,
    rolloutPercentage,
}: {
    variantKey: string
    rolloutPercentage: number
}): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { updateExperimentVariantImages, reportExperimentVariantScreenshotUploaded } = useActions(experimentLogic)

    const getInitialMediaIds = (): string[] => {
        const variantImages = experiment.parameters?.variant_screenshot_media_ids?.[variantKey]
        if (!variantImages) {
            return []
        }

        return Array.isArray(variantImages) ? variantImages : [variantImages]
    }

    // Local state so thumbnails update immediately, while the experiment save runs in the background
    const [mediaIds, setMediaIds] = useState<string[]>(getInitialMediaIds)

    return (
        <VariantScreenshotEditor
            mediaIds={mediaIds}
            onChange={(newMediaIds) => {
                setMediaIds(newMediaIds)
                updateExperimentVariantImages({
                    ...experiment.parameters?.variant_screenshot_media_ids,
                    [variantKey]: newMediaIds,
                })
            }}
            onUploaded={() => reportExperimentVariantScreenshotUploaded(experiment.id)}
            viewerTitle={
                <>
                    <VariantTag variantKey={variantKey} />
                    {rolloutPercentage !== undefined && (
                        <span className="text-secondary text-sm">({rolloutPercentage}% rollout)</span>
                    )}
                </>
            }
        />
    )
}

/**
 * Up to 5 screenshots for one variant: thumbnails, upload or paste, remove, and a full-size viewer.
 * Controlled, so it works on a saved experiment (`VariantScreenshot`) and on an unsaved draft (the wizard).
 */
export function VariantScreenshotEditor({
    mediaIds,
    onChange,
    onUploaded,
    viewerTitle,
    size = 'medium',
}: {
    mediaIds: string[]
    onChange: (mediaIds: string[]) => void
    /** Called after a new screenshot is uploaded and added */
    onUploaded?: () => void
    /** Shown next to "Screenshot N of M" in the full-size viewer */
    viewerTitle?: ReactNode
    /** `small` matches the height of a medium input, for use inline in a form row */
    size?: 'small' | 'medium'
}): JSX.Element {
    const [loadingImages, setLoadingImages] = useState<Record<string, boolean>>({})
    const [selectedImageIndex, setSelectedImageIndex] = useState<number | null>(null)

    const [isFocused, setIsFocused] = useState(false)
    const containerRef = useRef<HTMLDivElement>(null)

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (_, __, id) => {
            if (!id) {
                return
            }
            if (mediaIds.length >= 5) {
                lemonToast.error('Maximum of 5 images allowed')
                return
            }

            onChange([...mediaIds, id])
            onUploaded?.()
        },
        onError: (detail) => {
            lemonToast.error(`Error uploading image: ${detail}`)
        },
    })

    const handlePaste = useCallback(
        (e: React.ClipboardEvent): void => {
            if (uploading) {
                return
            }

            const items = e.clipboardData?.items
            if (!items) {
                return
            }

            for (let i = 0; i < items.length; i++) {
                const item = items[i]
                if (item.type.startsWith('image/')) {
                    e.preventDefault()
                    const file = item.getAsFile()
                    if (file) {
                        if (mediaIds.length >= 5) {
                            lemonToast.error('Maximum of 5 images allowed')
                            return
                        }
                        setFilesToUpload([file])
                    } else {
                        lemonToast.error('Could not read image from clipboard')
                    }
                    return
                }
            }
        },
        [mediaIds.length, setFilesToUpload, uploading]
    )

    const handleImageLoad = (mediaId: string): void => {
        setLoadingImages((prev) => ({ ...prev, [mediaId]: false }))
    }

    const handleImageError = (mediaId: string): void => {
        setLoadingImages((prev) => ({ ...prev, [mediaId]: false }))
    }

    const handleDelete = (indexToDelete: number): void => {
        onChange(mediaIds.filter((_, index) => index !== indexToDelete))
    }

    const getThumbnailWidth = (): string => {
        const totalItems = mediaIds.length < 5 ? mediaIds.length + 1 : mediaIds.length
        switch (totalItems) {
            case 1:
                return 'w-20'
            case 2:
                return 'w-20'
            case 3:
                return 'w-16'
            case 4:
                return 'w-14'
            case 5:
                return 'w-12'
            default:
                return 'w-20'
        }
    }

    const isSmall = size === 'small'
    const heightClass = isSmall ? 'h-[calc(2.125rem+3px)]' : 'h-16'
    const widthClass = isSmall ? 'w-14' : getThumbnailWidth()
    const addWidthClass = isSmall ? 'w-[calc(2.125rem+3px)]' : widthClass
    // In a form row, show only the first thumbnail (with a "+N" badge for the rest) at a fixed width, so adding
    // screenshots never resizes the row or reflows the table around it. The viewer shows and removes the rest.
    const visibleMediaIds = isSmall ? mediaIds.slice(0, 1) : mediaIds
    const hiddenCount = mediaIds.length - visibleMediaIds.length

    const getMediaSrc = (mediaId: string): string =>
        mediaId.startsWith('data:') ? mediaId : backendAssetUrl(`/uploaded_media/${mediaId}`)

    const showPrevious = (): void =>
        setSelectedImageIndex((prev) => (prev === null ? prev : (prev - 1 + mediaIds.length) % mediaIds.length))
    const showNext = (): void => setSelectedImageIndex((prev) => (prev === null ? prev : (prev + 1) % mediaIds.length))

    // Arrow-key navigation while the screenshot viewer is open.
    useEffect(() => {
        if (selectedImageIndex === null || mediaIds.length <= 1) {
            return
        }
        const onKeyDown = (e: KeyboardEvent): void => {
            if (e.key === 'ArrowLeft') {
                showPrevious()
            } else if (e.key === 'ArrowRight') {
                showNext()
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selectedImageIndex, mediaIds.length])

    return (
        <div
            ref={containerRef}
            className={`deprecated-space-y-4 rounded p-1 -m-1 outline-none transition-colors ${
                isFocused ? 'ring-1 ring-accent' : ''
            }`}
            tabIndex={0}
            onPaste={handlePaste}
            onFocus={() => setIsFocused(true)}
            onBlur={(e) => {
                if (!containerRef.current?.contains(e.relatedTarget as Node)) {
                    setIsFocused(false)
                }
            }}
        >
            <div className={`flex items-start ${isSmall ? 'gap-2 w-[calc(4rem+2.125rem+3px)] shrink-0' : 'gap-4'}`}>
                {visibleMediaIds.map((mediaId, index) => (
                    <div key={mediaId} className="relative">
                        <div
                            className={`text-secondary ${isSmall ? 'flex' : 'inline-flex'} flow-row items-center gap-1 cursor-pointer`}
                        >
                            <div onClick={() => setSelectedImageIndex(index)} className="cursor-zoom-in relative">
                                <div
                                    className={`relative flex overflow-hidden select-none ${widthClass} ${heightClass} rounded before:absolute before:inset-0 before:border before:rounded`}
                                >
                                    {loadingImages[mediaId] && <LemonSkeleton className="absolute inset-0" />}
                                    <img
                                        className="w-full h-full object-cover"
                                        src={getMediaSrc(mediaId)}
                                        alt={`Variant screenshot thumbnail ${index + 1}`}
                                        onError={() => handleImageError(mediaId)}
                                        onLoad={() => handleImageLoad(mediaId)}
                                    />
                                    {index === 0 && hiddenCount > 0 && (
                                        <span className="absolute bottom-0.5 right-0.5 rounded bg-surface-primary px-1 text-[10px] font-semibold leading-4">
                                            +{hiddenCount}
                                        </span>
                                    )}
                                </div>
                                <div className="absolute -inset-2 group">
                                    <LemonButton
                                        icon={<IconX />}
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            handleDelete(index)
                                        }}
                                        size="small"
                                        tooltip="Remove"
                                        tooltipPlacement="right"
                                        noPadding
                                        className="group-hover:flex hidden absolute right-0 top-0"
                                    />
                                </div>
                            </div>
                        </div>
                    </div>
                ))}

                {mediaIds.length < 5 && (
                    <div className={`relative ${addWidthClass} ${heightClass}`}>
                        <LemonFileInput
                            accept="image/*"
                            multiple={false}
                            onChange={setFilesToUpload}
                            loading={uploading}
                            value={filesToUpload}
                            showUploadedFiles={false}
                            callToAction={
                                <Tooltip title={isSmall ? 'Add a screenshot, or paste one with ⌘V' : undefined}>
                                    <div
                                        className={`flex items-center justify-center w-full ${heightClass} border border-dashed rounded cursor-pointer hover:border-accent`}
                                    >
                                        {uploading ? (
                                            <Spinner className="text-secondary" />
                                        ) : (
                                            <span className={`${isSmall ? 'text-lg' : 'text-2xl'} text-secondary`}>
                                                +
                                            </span>
                                        )}
                                    </div>
                                </Tooltip>
                            }
                        />
                    </div>
                )}
                {isFocused && !isSmall && mediaIds.length < 5 && (
                    <div className={`flex items-center ${heightClass}`}>
                        <span className="text-xs text-secondary whitespace-nowrap">⌘V to paste</span>
                    </div>
                )}
            </div>

            <LemonModal
                isOpen={selectedImageIndex !== null}
                onClose={() => setSelectedImageIndex(null)}
                width="90vw"
                maxWidth={1400}
                footer={
                    isSmall && selectedImageIndex !== null ? (
                        <LemonButton
                            type="secondary"
                            status="danger"
                            onClick={() => {
                                const remaining = mediaIds.length - 1
                                handleDelete(selectedImageIndex)
                                setSelectedImageIndex(
                                    remaining > 0 ? Math.min(selectedImageIndex, remaining - 1) : null
                                )
                            }}
                        >
                            Remove screenshot
                        </LemonButton>
                    ) : undefined
                }
                title={
                    <div className="flex items-center gap-2">
                        <span>
                            Screenshot {selectedImageIndex !== null ? selectedImageIndex + 1 : ''} of {mediaIds.length}
                        </span>
                        {viewerTitle && (
                            <>
                                <LemonDivider className="my-0 mx-1" vertical />
                                {viewerTitle}
                            </>
                        )}
                    </div>
                }
            >
                {selectedImageIndex !== null && mediaIds[selectedImageIndex] && (
                    <div className="flex items-center gap-2">
                        {mediaIds.length > 1 && (
                            <LemonButton
                                icon={<IconChevronLeft />}
                                onClick={showPrevious}
                                size="large"
                                tooltip="Previous screenshot"
                                aria-label="Previous screenshot"
                            />
                        )}
                        <ZoomableImage
                            src={getMediaSrc(mediaIds[selectedImageIndex])}
                            alt={`Screenshot ${selectedImageIndex + 1}`}
                            resetKey={selectedImageIndex}
                            className="flex-1 h-[80vh]"
                        />
                        {mediaIds.length > 1 && (
                            <LemonButton
                                icon={<IconChevronRight />}
                                onClick={showNext}
                                size="large"
                                tooltip="Next screenshot"
                                aria-label="Next screenshot"
                            />
                        )}
                    </div>
                )}
            </LemonModal>
        </div>
    )
}
