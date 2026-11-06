import { ReactNode, useEffect, useState } from 'react'

import { Link } from '@posthog/lemon-ui'

import { aiBlobRenderHandlers } from '../aiBlob'
import {
    canLoadImageWhileEmbedded,
    useConversationDisplayEmbedded,
} from '../ConversationDisplay/conversationDisplayEmbedded'

interface AIImageProps {
    src: string
    alt: string
    className?: string
    fallback: ReactNode
}

export function AIImage({ src, alt, className, fallback }: AIImageProps): JSX.Element {
    const [failedSrc, setFailedSrc] = useState<string | null>(null)
    useEffect(() => setFailedSrc(null), [src])
    const handlers = aiBlobRenderHandlers(src, 'image')
    const embedded = useConversationDisplayEmbedded()

    if (embedded && !canLoadImageWhileEmbedded(src)) {
        return (
            <Link to={src} target="_blank" targetBlankIcon>
                {alt}
            </Link>
        )
    }
    if (failedSrc === src) {
        return <>{fallback}</>
    }
    return (
        <img
            src={src}
            alt={alt}
            className={className}
            data-attr="ai-message-image"
            onLoad={handlers.onLoad}
            onError={() => {
                handlers.onError?.()
                setFailedSrc(src)
            }}
        />
    )
}
