import { useActions, useValues } from 'kea'

import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@posthog/quill'

import { featurePreviewsLogic } from './featurePreviewsLogic'

export function QuillFeaturePreviewImageDialog(): JSX.Element {
    const { expandedImageFlagKey, earlyAccessFeatures } = useValues(featurePreviewsLogic)
    const { closeFeaturePreviewImage } = useActions(featurePreviewsLogic)

    const feature = earlyAccessFeatures.find((f) => f.flagKey === expandedImageFlagKey)

    return (
        <Dialog open={!!feature?.imageUrl} onOpenChange={(open: boolean) => !open && closeFeaturePreviewImage()}>
            <DialogContent size="wide" data-attr="feature-preview-image-dialog">
                <DialogHeader>
                    <DialogTitle>{feature?.name}</DialogTitle>
                    {feature?.description && <DialogDescription>{feature.description}</DialogDescription>}
                </DialogHeader>
                <DialogBody>
                    {feature?.imageUrl && (
                        <img
                            src={feature.imageUrl}
                            alt={`Preview of ${feature.name}`}
                            className="block h-auto w-full rounded-md border"
                        />
                    )}
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}
