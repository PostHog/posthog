import { useActions, useValues } from 'kea'

import { IconImage, IconX } from '@posthog/icons'
import { LemonButton, LemonFileInput, LemonLabel } from '@posthog/lemon-ui'

import { preflightLogic } from 'lib/logic/preflightLogic'
import { backendAssetUrl } from 'lib/utils/apiHost'

import { featureRequestsLogic } from './featureRequestsLogic'

export function FeatureRequestEvidenceImagePicker(): JSX.Element {
    const { objectStorageAvailable } = useValues(preflightLogic)
    const { evidenceFilesToUpload, evidenceImageIds, uploadingEvidenceImages } = useValues(featureRequestsLogic)
    const { uploadEvidenceImages, removeEvidenceImage } = useActions(featureRequestsLogic)
    const uploadDisabledReason = uploadingEvidenceImages
        ? 'Uploading images'
        : objectStorageAvailable
          ? undefined
          : 'Enable object storage to add images to evidence'

    return (
        <div className="flex flex-col gap-2">
            <LemonLabel>Images</LemonLabel>
            {evidenceImageIds.length > 0 && (
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                    {evidenceImageIds.map((imageId) => (
                        <div
                            key={imageId}
                            className="group relative aspect-video overflow-hidden rounded border bg-bg-light"
                        >
                            <img
                                src={backendAssetUrl(`/uploaded_media/${imageId}`)}
                                alt="Evidence attachment"
                                className="h-full w-full object-contain"
                            />
                            <LemonButton
                                type="secondary"
                                status="danger"
                                size="xsmall"
                                icon={<IconX />}
                                onClick={() => removeEvidenceImage(imageId)}
                                aria-label="Remove image"
                                className="absolute right-1 top-1 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100"
                                data-attr="remove-feature-request-evidence-image"
                            />
                        </div>
                    ))}
                </div>
            )}
            <LemonFileInput
                accept="image/*"
                multiple
                onChange={uploadEvidenceImages}
                loading={uploadingEvidenceImages}
                value={evidenceFilesToUpload}
                showUploadedFiles={false}
                disabledReason={uploadDisabledReason}
                callToAction={
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconImage />}
                        loading={uploadingEvidenceImages}
                        disabledReason={uploadDisabledReason}
                        data-attr="upload-feature-request-evidence-images"
                    >
                        Add images
                    </LemonButton>
                }
            />
        </div>
    )
}
