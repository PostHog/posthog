import { useValues } from 'kea'
import { useCallback, useRef, useState } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { HeatmapCanvas } from 'lib/components/heatmaps/HeatmapCanvas'
import { heatmapsBrowserLogic } from 'scenes/heatmaps/heatmapsBrowserLogic'

export function ScreenshotHeatmapBrowser(): JSX.Element {
    const logic = heatmapsBrowserLogic()
    const { widthOverride, screenshotUrl, screenshotLoading, generatingScreenshot } = useValues(logic)

    const [actualImageDimensions, setActualImageDimensions] = useState<{ width: number; height: number } | null>(null)
    const imageRef = useRef<HTMLImageElement>(null)

    const handleImageLoad = useCallback(() => {
        if (imageRef.current) {
            const { offsetWidth, offsetHeight } = imageRef.current
            setActualImageDimensions({ width: offsetWidth, height: offsetHeight })
        }
    }, [])

    return (
        <div className="relative flex w-full justify-center flex-1">
            <div
                className="relative"
                // Use actual image width if available, otherwise fall back to widthOverride
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width: actualImageDimensions?.width ?? widthOverride ?? '100%' }}
            >
                {(screenshotLoading || generatingScreenshot) && (
                    <div className="absolute inset-0 flex items-center justify-center">
                        <Spinner />
                    </div>
                )}
                {screenshotUrl && (
                    <>
                        <HeatmapCanvas
                            positioning="absolute"
                            widthOverride={actualImageDimensions?.width ?? widthOverride}
                            context="in-app"
                        />
                        <img
                            ref={imageRef}
                            src={screenshotUrl}
                            style={{ maxWidth: widthOverride ?? '100%', height: 'auto', display: 'block' }}
                            onLoad={handleImageLoad}
                            onError={() => {
                                console.error('Failed to load screenshot')
                            }}
                        />
                    </>
                )}
            </div>
        </div>
    )
}
