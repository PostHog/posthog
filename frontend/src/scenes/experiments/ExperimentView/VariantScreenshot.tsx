import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { IconChevronLeft, IconChevronRight, IconX } from '@posthog/icons'
import {
    LemonButton,
    LemonDivider,
    LemonFileInput,
    LemonModal,
    LemonSkeleton,
    lemonToast,
    Spinner,
} from '@posthog/lemon-ui'

import { ZoomableImage } from 'lib/components/ZoomableImage/ZoomableImage'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { backendAssetUrl } from 'lib/utils/apiHost'

import { experimentLogic } from '../experimentLogic'
import { getExperimentVariants } from '../utils'
import { VariantTag } from './VariantTag'

interface ViewerScreenshot {
    variantKey: string
    rolloutPercentage: number | undefined
    mediaId: string
}

function toMediaIds(value: string | string[] | undefined): string[] {
    if (!value) {
        return []
    }
    return Array.isArray(value) ? value : [value]
}

export function VariantScreenshot({
    variantKey,
    rolloutPercentage,
}: {
    variantKey: string
    rolloutPercentage: number
}): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { updateExperimentVariantImages, reportExperimentVariantScreenshotUploaded } = useActions(experimentLogic)

    const [mediaIds, setMediaIds] = useState<string[]>(() =>
        toMediaIds(experiment.parameters?.variant_screenshot_media_ids?.[variantKey])
    )
    const [loadingImages, setLoadingImages] = useState<Record<string, boolean>>({})
    const [selectedKey, setSelectedKey] = useState<{ variantKey: string; mediaId: string } | null>(null)

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

            setMediaIds((prev) => {
                const newMediaIds = [...prev, id]
                const updatedVariantImages = {
                    ...experiment.parameters?.variant_screenshot_media_ids,
                    [variantKey]: newMediaIds,
                }

                updateExperimentVariantImages(updatedVariantImages)
                reportExperimentVariantScreenshotUploaded(experiment.id)
                return newMediaIds
            })
        },
        onError: (detail) => {
            lemonToast.error(`Error uploading image: ${detail}`)
        },
    })

    const handlePaste = useCallback(
        (e: React.ClipboardEvent): void => {
            // The viewer can show another variant, and a paste there would save to this row's variant.
            if (uploading || selectedKey !== null) {
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
        [mediaIds.length, setFilesToUpload, uploading, selectedKey]
    )

    const handleImageLoad = (mediaId: string): void => {
        setLoadingImages((prev) => ({ ...prev, [mediaId]: false }))
    }

    const handleImageError = (mediaId: string): void => {
        setLoadingImages((prev) => ({ ...prev, [mediaId]: false }))
    }

    const handleDelete = (indexToDelete: number): void => {
        const newMediaIds = mediaIds.filter((_, index) => index !== indexToDelete)
        setMediaIds(newMediaIds)

        const updatedVariantImages = {
            ...experiment.parameters?.variant_screenshot_media_ids,
            [variantKey]: newMediaIds,
        }

        updateExperimentVariantImages(updatedVariantImages)
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

    const widthClass = getThumbnailWidth()

    const getMediaSrc = (mediaId: string): string =>
        mediaId.startsWith('data:') ? mediaId : backendAssetUrl(`/uploaded_media/${mediaId}`)

    // The viewer steps through every variant's screenshots in table order, so people can compare variants.
    // This variant uses its local list, because a new upload reaches the experiment only after the save.
    const viewerScreenshots = useMemo((): ViewerScreenshot[] => {
        const savedMediaIds = experiment.parameters?.variant_screenshot_media_ids ?? {}
        // Match the distribution table, which scales variant rollouts down by the holdout share.
        const holdoutFactor = (100 - (experiment.holdout?.filters[0]?.rollout_percentage || 0)) / 100
        const variants = getExperimentVariants(experiment)
        const orderedVariants = variants.some((variant) => variant.key === variantKey)
            ? variants
            : [...variants, { key: variantKey, rollout_percentage: rolloutPercentage }]
        return orderedVariants.flatMap((variant) =>
            (variant.key === variantKey ? mediaIds : toMediaIds(savedMediaIds[variant.key])).map((mediaId) => ({
                variantKey: variant.key,
                rolloutPercentage:
                    variant.key === variantKey
                        ? rolloutPercentage
                        : variant.rollout_percentage !== undefined
                          ? variant.rollout_percentage * holdoutFactor
                          : undefined,
                mediaId,
            }))
        )
    }, [experiment, variantKey, rolloutPercentage, mediaIds])

    // Find the selection by identity, so an upload or delete in another variant does not change the open screenshot.
    const foundIndex = selectedKey
        ? viewerScreenshots.findIndex(
              (screenshot) =>
                  screenshot.variantKey === selectedKey.variantKey && screenshot.mediaId === selectedKey.mediaId
          )
        : -1
    const selectedImageIndex = foundIndex === -1 ? null : foundIndex
    const selectedScreenshot = selectedImageIndex !== null ? viewerScreenshots[selectedImageIndex] : undefined

    const openViewer = (mediaId: string): void => {
        setSelectedKey({ variantKey, mediaId })
    }

    const step = (offset: number): void => {
        if (selectedImageIndex === null || viewerScreenshots.length === 0) {
            return
        }
        const nextIndex = (selectedImageIndex + offset + viewerScreenshots.length) % viewerScreenshots.length
        const fromVariant = viewerScreenshots[selectedImageIndex]?.variantKey
        const toVariant = viewerScreenshots[nextIndex]?.variantKey
        if (fromVariant !== toVariant) {
            posthog.capture('experiment variant screenshot viewer switched variant', {
                experiment_id: experiment.id,
                direction: offset > 0 ? 'next' : 'previous',
                variant_count: new Set(viewerScreenshots.map((screenshot) => screenshot.variantKey)).size,
            })
        }
        const next = viewerScreenshots[nextIndex]
        setSelectedKey({ variantKey: next.variantKey, mediaId: next.mediaId })
    }
    const showPrevious = (): void => step(-1)
    const showNext = (): void => step(1)

    // Arrow-key navigation while the screenshot viewer is open.
    useEffect(() => {
        if (selectedImageIndex === null || viewerScreenshots.length <= 1) {
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
    }, [selectedImageIndex, viewerScreenshots])

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
            <div className="flex gap-4 items-start">
                {mediaIds.map((mediaId, index) => (
                    <div key={mediaId} className="relative">
                        <div className="text-secondary inline-flex flow-row items-center gap-1 cursor-pointer">
                            <div onClick={() => openViewer(mediaId)} className="cursor-zoom-in relative">
                                <div
                                    className={`relative flex overflow-hidden select-none ${widthClass} h-16 rounded before:absolute before:inset-0 before:border before:rounded`}
                                >
                                    {loadingImages[mediaId] && <LemonSkeleton className="absolute inset-0" />}
                                    <img
                                        className="w-full h-full object-cover"
                                        src={getMediaSrc(mediaId)}
                                        alt={`Variant screenshot thumbnail ${index + 1}`}
                                        onError={() => handleImageError(mediaId)}
                                        onLoad={() => handleImageLoad(mediaId)}
                                    />
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
                    <div className={`relative ${widthClass} h-16`}>
                        <LemonFileInput
                            accept="image/*"
                            multiple={false}
                            onChange={setFilesToUpload}
                            loading={uploading}
                            value={filesToUpload}
                            showUploadedFiles={false}
                            callToAction={
                                <div className="flex items-center justify-center w-full h-16 border border-dashed rounded cursor-pointer hover:border-accent">
                                    {uploading ? (
                                        <Spinner className="text-secondary" />
                                    ) : (
                                        <span className="text-2xl text-secondary">+</span>
                                    )}
                                </div>
                            }
                        />
                    </div>
                )}
                {isFocused && mediaIds.length < 5 && (
                    <div className="flex items-center h-16">
                        <span className="text-xs text-secondary whitespace-nowrap">⌘V to paste</span>
                    </div>
                )}
            </div>

            <LemonModal
                isOpen={selectedImageIndex !== null}
                onClose={() => setSelectedKey(null)}
                width="90vw"
                maxWidth={1400}
                title={
                    selectedScreenshot ? (
                        <div className="flex items-center gap-2">
                            <span>
                                Screenshot {(selectedImageIndex ?? 0) + 1} of {viewerScreenshots.length}
                            </span>
                            <LemonDivider className="my-0 mx-1" vertical />
                            <VariantTag variantKey={selectedScreenshot.variantKey} />
                            {selectedScreenshot.rolloutPercentage !== undefined && (
                                <span className="text-secondary text-sm">
                                    ({selectedScreenshot.rolloutPercentage}% rollout)
                                </span>
                            )}
                        </div>
                    ) : null
                }
            >
                {selectedScreenshot && (
                    <div className="flex items-center gap-2">
                        {viewerScreenshots.length > 1 && (
                            <LemonButton
                                icon={<IconChevronLeft />}
                                onClick={showPrevious}
                                size="large"
                                tooltip="Previous screenshot"
                                aria-label="Previous screenshot"
                            />
                        )}
                        <ZoomableImage
                            src={getMediaSrc(selectedScreenshot.mediaId)}
                            alt={`Screenshot ${(selectedImageIndex ?? 0) + 1}: ${selectedScreenshot.variantKey}`}
                            resetKey={selectedImageIndex ?? undefined}
                            className="flex-1 h-[80vh]"
                        />
                        {viewerScreenshots.length > 1 && (
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
