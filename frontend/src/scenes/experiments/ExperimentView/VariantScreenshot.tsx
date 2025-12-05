import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonFileInput, LemonModal, LemonSkeleton, lemonToast } from '@posthog/lemon-ui'

import { useUploadFiles } from 'lib/hooks/useUploadFiles'

import { experimentLogic } from '../experimentLogic'
import { VariantTag } from './components'

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

    const [mediaIds, setMediaIds] = useState<string[]>(getInitialMediaIds())
    const [loadingImages, setLoadingImages] = useState<Record<string, boolean>>({})
    const [selectedImageIndex, setSelectedImageIndex] = useState<number | null>(null)

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (_, __, id) => {
            if (id && mediaIds.length < 5) {
                const newMediaIds = [...mediaIds, id]
                setMediaIds(newMediaIds)

                const updatedVariantImages = {
                    ...experiment.parameters?.variant_screenshot_media_ids,
                    [variantKey]: newMediaIds,
                }

                updateExperimentVariantImages(updatedVariantImages)
                reportExperimentVariantScreenshotUploaded(experiment.id)
            } else if (mediaIds.length >= 5) {
                lemonToast.error('Maximum of 5 images allowed')
            }
        },
        onError: (detail) => {
            lemonToast.error(`Error uploading image: ${detail}`)
        },
    })

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

    return (
        <div className="deprecated-space-y-4">
            <div className="flex gap-4 items-start">
                {mediaIds.map((mediaId, index) => (
                    <div key={mediaId} className="relative">
                        <div className="text-secondary inline-flex flow-row items-center gap-1 cursor-pointer">
                            <div onClick={() => setSelectedImageIndex(index)} className="cursor-zoom-in relative">
                                <div
                                    className={`relative flex overflow-hidden select-none ${widthClass} h-16 rounded before:absolute before:inset-0 before:border before:rounded`}
                                >
                                    {loadingImages[mediaId] && <LemonSkeleton className="absolute inset-0" />}
                                    <img
                                        className="w-full h-full object-cover"
                                        src={mediaId.startsWith('data:') ? mediaId : `/uploaded_media/${mediaId}`}
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
                            callToAction={
                                <div className="flex items-center justify-center w-full h-16 border border-dashed rounded cursor-pointer hover:border-accent">
                                    <span className="text-2xl text-secondary">+</span>
                                </div>
                            }
                        />
                    </div>
                )}
            </div>

            <LemonModal
                isOpen={selectedImageIndex !== null}
                onClose={() => setSelectedImageIndex(null)}
                title={
                    <div className="flex items-center gap-2">
                        <span>Screenshot {selectedImageIndex !== null ? selectedImageIndex + 1 : ''}</span>
                        <LemonDivider className="my-0 mx-1" vertical />
                        <VariantTag variantKey={variantKey} />
                        {rolloutPercentage !== undefined && (
                            <span className="text-secondary text-sm">({rolloutPercentage}% rollout)</span>
                        )}
                    </div>
                }
            >
                {selectedImageIndex !== null && mediaIds[selectedImageIndex] && (
                    <img
                        src={
                            mediaIds[selectedImageIndex]?.startsWith('data:')
                                ? mediaIds[selectedImageIndex]
                                : `/uploaded_media/${mediaIds[selectedImageIndex]}`
                        }
                        alt={`Screenshot ${selectedImageIndex + 1}: ${variantKey}`}
                        className="max-w-full max-h-[80vh] overflow-auto"
                    />
                )}
            </LemonModal>
        </div>
    )
}

export default VariantScreenshot
