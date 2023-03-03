import clsx from 'clsx'
import { getSeriesColor } from 'lib/colors'
import { useState } from 'react'

export function FallbackCoverImage({
    src,
    alt,
    index,
    className = '',
}: {
    src: string | undefined
    alt: string
    index: number
    className?: string
}): JSX.Element {
    const [hasError, setHasError] = useState(false)

    const handleImageError = (): void => {
        setHasError(true)
    }

    return (
        <>
            {hasError || !src ? (
                <div
                    className={clsx('w-full h-full', className)}
                    // dynamic color based on index
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        background: getSeriesColor(index),
                    }}
                />
            ) : (
                <img
                    className="w-full h-full object-cover object-center"
                    src={src}
                    alt={alt}
                    onError={handleImageError}
                />
            )}
        </>
    )
}
