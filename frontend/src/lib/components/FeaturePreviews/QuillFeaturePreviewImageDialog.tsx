import { useActions, useValues } from 'kea'

import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@posthog/quill'

import { EnrichedEarlyAccessFeature, featurePreviewsLogic } from './featurePreviewsLogic'

export interface QuillFeaturePreviewImageDialogProps {
    /** The features of one section. Each section has its own dialog, so only one opens. */
    features: EnrichedEarlyAccessFeature[]
}

export function QuillFeaturePreviewImageDialog({ features }: QuillFeaturePreviewImageDialogProps): JSX.Element {
    const { expandedImageFlagKey } = useValues(featurePreviewsLogic)
    const { closeFeaturePreviewImage } = useActions(featurePreviewsLogic)

    const feature = features.find((f) => f.flagKey === expandedImageFlagKey)

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
