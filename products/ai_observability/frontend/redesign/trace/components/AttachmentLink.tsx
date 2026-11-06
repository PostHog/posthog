import { Link } from '@posthog/lemon-ui'

import { AttachmentUrlKind } from './attachmentUrl'

export interface AttachmentLinkProps {
    url: string
    urlKind: AttachmentUrlKind
    downloadName: string
    linkDataAttr: string
    downloadDataAttr: string
    className?: string
    children: React.ReactNode
}

export function AttachmentLink({
    url,
    urlKind,
    downloadName,
    linkDataAttr,
    downloadDataAttr,
    className,
    children,
}: AttachmentLinkProps): JSX.Element {
    if (urlKind === 'external' || urlKind === 'sameOrigin') {
        return (
            <Link
                to={url}
                target="_blank"
                disableClientSideRouting={urlKind === 'sameOrigin'}
                className={className}
                data-attr={linkDataAttr}
            >
                {children}
            </Link>
        )
    }
    if (urlKind === 'data') {
        return (
            // eslint-disable-next-line react/forbid-elements
            <a href={url} download={downloadName} className={className} data-attr={downloadDataAttr}>
                {children}
            </a>
        )
    }
    return <>{children}</>
}
