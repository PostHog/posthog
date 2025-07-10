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
            <div className="flex items-start gap-4">
                {mediaIds.map((mediaId, index) => (
                    <div key={mediaId} className="relative">
                        <div className="text-secondary flow-row inline-flex cursor-pointer items-center gap-1">
                            <div onClick={() => setSelectedImageIndex(index)} className="relative cursor-zoom-in">
                                <div
                                    className={`relative flex select-none overflow-hidden ${widthClass} h-16 rounded before:absolute before:inset-0 before:rounded before:border`}
                                >
                                    {loadingImages[mediaId] && <LemonSkeleton className="absolute inset-0" />}
                                    <img
                                        className="h-full w-full object-cover"
                                        src={mediaId.startsWith('data:') ? mediaId : `/uploaded_media/${mediaId}`}
                                        onError={() => handleImageError(mediaId)}
                                        onLoad={() => handleImageLoad(mediaId)}
                                    />
                                </div>
                                <div className="group absolute -inset-2">
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
                                        className="absolute right-0 top-0 hidden group-hover:flex"
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
                                <div className="hover:border-accent flex h-16 w-full cursor-pointer items-center justify-center rounded border border-dashed">
                                    <span className="text-secondary text-2xl">+</span>
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
                        <LemonDivider className="mx-1 my-0" vertical />
                        <VariantTag experimentId={experiment.id} variantKey={variantKey} />
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
                        className="max-h-[80vh] max-w-full overflow-auto"
                    />
                )}
            </LemonModal>
        </div>
    )
}

export default VariantScreenshot
