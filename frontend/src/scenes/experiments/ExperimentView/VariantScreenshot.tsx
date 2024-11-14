import { IconUpload, IconX } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonFileInput, LemonModal, LemonSkeleton, lemonToast } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { useState } from 'react'

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

    const [mediaId, setMediaId] = useState(experiment.parameters?.variant_screenshot_media_ids?.[variantKey] || null)
    const [isLoadingImage, setIsLoadingImage] = useState(true)
    const [isModalOpen, setIsModalOpen] = useState(false)

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (_, __, id) => {
            setMediaId(id)
            if (id) {
                const updatedVariantImages = {
                    ...experiment.parameters?.variant_screenshot_media_ids,
                    [variantKey]: id,
                }
                updateExperimentVariantImages(updatedVariantImages)
                reportExperimentVariantScreenshotUploaded(experiment.id)
            }
        },
        onError: (detail) => {
            lemonToast.error(`Error uploading image: ${detail}`)
        },
    })

    return (
        <div className="space-y-4">
            {!mediaId ? (
                <LemonFileInput
                    accept="image/*"
                    multiple={false}
                    onChange={setFilesToUpload}
                    loading={uploading}
                    value={filesToUpload}
                    callToAction={
                        <>
                            <IconUpload className="text-2xl" />
                            <span>Upload a preview of this variant's UI</span>
                        </>
                    }
                />
            ) : (
                <div className="relative">
                    <div className="text-muted inline-flex flow-row items-center gap-1 cursor-pointer">
                        <div onClick={() => setIsModalOpen(true)} className="cursor-zoom-in relative">
                            <div className="relative flex overflow-hidden select-none size-20 w-full rounded before:absolute before:inset-0 before:border before:rounded">
                                {isLoadingImage && <LemonSkeleton className="absolute inset-0" />}
                                <img
                                    className="size-full object-cover"
                                    src={mediaId.startsWith('data:') ? mediaId : `/uploaded_media/${mediaId}`}
                                    onError={() => setIsLoadingImage(false)}
                                    onLoad={() => setIsLoadingImage(false)}
                                />
                            </div>
                            <div className="absolute -inset-2 group">
                                <LemonButton
                                    icon={<IconX />}
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        setMediaId(null)
                                        const updatedVariantImages = {
                                            ...experiment.parameters?.variant_screenshot_media_ids,
                                        }
                                        delete updatedVariantImages[variantKey]
                                        updateExperimentVariantImages(updatedVariantImages)
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
            )}
            <LemonModal
                isOpen={isModalOpen}
                onClose={() => setIsModalOpen(false)}
                title={
                    <div className="flex items-center gap-2">
                        <span>Screenshot</span>
                        <LemonDivider className="my-0 mx-1" vertical />
                        <VariantTag experimentId={experiment.id} variantKey={variantKey} />
                        {rolloutPercentage !== undefined && (
                            <span className="text-muted text-sm">({rolloutPercentage}% rollout)</span>
                        )}
                    </div>
                }
            >
                <img
                    src={mediaId?.startsWith('data:') ? mediaId : `/uploaded_media/${mediaId}`}
                    alt={`Screenshot: ${variantKey}`}
                    className="max-w-full max-h-[80vh] overflow-auto"
                />
            </LemonModal>
        </div>
    )
}
