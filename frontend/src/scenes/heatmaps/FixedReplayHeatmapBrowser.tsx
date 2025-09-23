import { useActions, useValues } from 'kea'
import React, { useEffect } from 'react'

import { HeatmapCanvas } from 'lib/components/heatmaps/HeatmapCanvas'
import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { heatmapsBrowserLogic } from 'scenes/heatmaps/heatmapsBrowserLogic'

export function FixedReplayHeatmapBrowser({
    iframeRef,
}: {
    iframeRef?: React.MutableRefObject<HTMLIFrameElement | null>
}): JSX.Element | null {
    const logic = heatmapsBrowserLogic()

    const { replayIframeData, hasValidReplayIframeData, widthOverride } = useValues(logic)
    const { onIframeLoad, setIframeWidth } = useActions(logic)

    const { setWindowWidthOverride } = useActions(heatmapDataLogic({ context: 'in-app' }))

    const { width: iframeWidth } = useResizeObserver<HTMLIFrameElement>({ ref: iframeRef })
    useEffect(() => {
        if (widthOverride === null) {
            setIframeWidth(iframeWidth ?? null)
        }
        setWindowWidthOverride(widthOverride)
    }, [iframeWidth, setIframeWidth, widthOverride, setWindowWidthOverride])

    return hasValidReplayIframeData ? (
        <div className="flex flex-row gap-x-2 w-full">
            <div className="relative flex-1 w-full h-full">
                <div className="flex justify-center h-full w-full overflow-scroll">
                    <div
                        className="relative h-full overflow-scroll"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: widthOverride ?? '100%' }}
                    >
                        <HeatmapCanvas positioning="absolute" widthOverride={widthOverride} context="in-app" />
                        <iframe
                            ref={iframeRef}
                            className="w-full h-full bg-white"
                            srcDoc={replayIframeData?.html}
                            onLoad={onIframeLoad}
                            allow=""
                        />
                    </div>
                </div>
            </div>
        </div>
    ) : null
}
