import { useState } from 'react'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton/LemonSkeleton'

interface DeploymentPreviewImageProps {
    src: string
    alt: string
    className?: string
    failed?: boolean
}

export function DeploymentPreviewImage({ src, alt, className, failed }: DeploymentPreviewImageProps): JSX.Element {
    const [loading, setLoading] = useState(!!src && !failed)
    const [errored, setErrored] = useState(false)
    const showImage = !failed && !!src && !errored

    return (
        <div className={`relative overflow-hidden bg-surface-secondary rounded ${className ?? ''}`}>
            {failed && (
                <div className="absolute inset-0 flex items-center justify-center text-danger text-sm font-semibold">
                    Build failed
                </div>
            )}
            {!failed && loading && <LemonSkeleton className="absolute inset-0 w-full h-full" />}
            {!failed && !loading && !showImage && (
                <div className="absolute inset-0 flex items-center justify-center text-secondary text-sm">
                    No preview
                </div>
            )}
            {showImage && (
                <img
                    src={src}
                    alt={alt}
                    className="w-full h-full object-cover"
                    onLoad={() => setLoading(false)}
                    onError={() => {
                        setLoading(false)
                        setErrored(true)
                    }}
                />
            )}
        </div>
    )
}
