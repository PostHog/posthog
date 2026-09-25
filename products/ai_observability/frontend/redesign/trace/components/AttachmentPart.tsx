import { IconDocument } from '@posthog/icons'
import { LemonTag, Link } from '@posthog/lemon-ui'

export interface AttachmentPartProps {
    label: string
    url?: string
}

export function AttachmentPart({ label, url }: AttachmentPartProps): JSX.Element {
    const tag = <LemonTag icon={<IconDocument />}>{label}</LemonTag>
    return url ? (
        <Link to={url} target="_blank">
            {tag}
        </Link>
    ) : (
        tag
    )
}
