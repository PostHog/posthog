import { AIImage } from '../../../components/AIImage'
import { AttachmentLink } from './AttachmentLink'
import { classifyAttachmentUrl } from './attachmentUrl'

export interface AttachmentImageProps {
    url: string
    alt: string
}

export function AttachmentImage({ url, alt }: AttachmentImageProps): JSX.Element {
    const image = (
        <AIImage
            src={url}
            alt={alt}
            className="block max-h-48 max-w-full rounded border border-primary object-contain"
            fallback={<span className="break-all">{url}</span>}
        />
    )
    const urlKind = classifyAttachmentUrl(url)
    if (urlKind === null) {
        return image
    }
    return (
        <AttachmentLink
            url={url}
            urlKind={urlKind}
            downloadName={alt}
            linkDataAttr="trace-view-attachment-image-link"
            downloadDataAttr="trace-view-attachment-image-download"
        >
            {image}
        </AttachmentLink>
    )
}
