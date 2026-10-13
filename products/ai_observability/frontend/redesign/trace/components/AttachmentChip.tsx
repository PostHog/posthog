import { IconDocument } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { AttachmentLink } from './AttachmentLink'
import { classifyAttachmentUrl } from './attachmentUrl'

export interface AttachmentChipProps {
    label: string
    url: string | null
}

export function AttachmentChip({ label, url }: AttachmentChipProps): JSX.Element {
    const chip = (
        <LemonTag icon={<IconDocument />} className="self-start">
            {label}
        </LemonTag>
    )
    if (!url) {
        return chip
    }
    return (
        <AttachmentLink
            url={url}
            urlKind={classifyAttachmentUrl(url)}
            downloadName={label}
            linkDataAttr="trace-view-attachment-link"
            downloadDataAttr="trace-view-attachment-download"
            className="self-start"
        >
            {chip}
        </AttachmentLink>
    )
}
