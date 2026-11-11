import { AttachmentMediaType } from '../types'
import { AttachmentChip } from './AttachmentChip'
import { AttachmentImage } from './AttachmentImage'
import { classifyAttachmentUrl } from './attachmentUrl'

export interface AttachmentPartProps {
    mediaType: AttachmentMediaType
    name: string | null
    mimeType: string | null
    url: string | null
}

export function AttachmentPart({ mediaType, name, mimeType, url }: AttachmentPartProps): JSX.Element {
    if (url === null) {
        return <AttachmentChip label={name ?? mimeType ?? mediaType} url={null} />
    }
    const isMediaPlayer = mediaType === 'audio' || mediaType === 'video'
    const urlKind = classifyAttachmentUrl(url)
    const canPlayInline = urlKind === 'data' || urlKind === 'sameOrigin'
    // The CSP's media-src blocks external audio/video, so those fall back to a chip.
    if (urlKind === null || mediaType === 'file' || (isMediaPlayer && !canPlayInline)) {
        return <AttachmentChip label={name ?? mimeType ?? mediaType} url={url} />
    }
    const caption = [name, mimeType].filter((value): value is string => value !== null).join(' · ')
    return (
        <figure className="m-0 flex max-w-full flex-col items-start gap-1">
            {mediaType === 'image' ? (
                <AttachmentImage url={url} alt={name ?? 'Attached image'} />
            ) : mediaType === 'audio' ? (
                <audio controls src={url} className="max-w-full" aria-label={caption || mediaType} />
            ) : (
                <video
                    controls
                    src={url}
                    className="max-h-48 max-w-full rounded border border-primary"
                    aria-label={caption || mediaType}
                />
            )}
            {caption ? <figcaption className="break-all text-xs text-secondary">{caption}</figcaption> : null}
        </figure>
    )
}
