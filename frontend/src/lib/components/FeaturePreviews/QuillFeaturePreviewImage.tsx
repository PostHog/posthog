import { useActions } from 'kea'

import { IconExpand45 } from '@posthog/icons'
import {
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
    cn,
} from '@posthog/quill'

import { EnrichedEarlyAccessFeature, featurePreviewsLogic } from './featurePreviewsLogic'

export interface QuillFeaturePreviewImageProps {
    feature: EnrichedEarlyAccessFeature
    /** Sets the size. The image fills it and crops to the top. */
    className?: string
}

export function QuillFeaturePreviewImage({ feature, className }: QuillFeaturePreviewImageProps): JSX.Element {
    const { openFeaturePreviewImage } = useActions(featurePreviewsLogic)

    return (
        <Dialog onOpenChange={(open: boolean) => open && openFeaturePreviewImage(feature.flagKey)}>
            <DialogTrigger
                render={
                    <button
                        type="button"
                        className={cn(
                            'group/image relative block cursor-zoom-in overflow-hidden rounded-md border bg-muted',
                            className
                        )}
                        aria-label={`View a larger image of ${feature.name}`}
                        data-attr="feature-preview-image"
                    />
                }
            >
                <img src={feature.imageUrl} alt="" loading="lazy" className="block size-full object-cover object-top" />
                <span className="absolute right-1 bottom-1 flex rounded-sm bg-background p-1 text-foreground opacity-0 shadow-sm transition-opacity group-hover/image:opacity-100 group-focus-visible/image:opacity-100">
                    <IconExpand45 />
                </span>
            </DialogTrigger>
            <DialogContent size="wide" data-attr="feature-preview-image-dialog">
                <DialogHeader>
                    <DialogTitle>{feature.name}</DialogTitle>
                    {feature.description && <DialogDescription>{feature.description}</DialogDescription>}
                </DialogHeader>
                <DialogBody>
                    <img
                        src={feature.imageUrl}
                        alt={`Preview of ${feature.name}`}
                        className="block h-auto w-full rounded-md border"
                    />
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}
