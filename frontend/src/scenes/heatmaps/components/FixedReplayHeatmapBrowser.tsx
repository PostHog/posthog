import { useActions, useValues } from 'kea'
import React from 'react'

import { HeatmapCanvas } from 'lib/components/heatmaps/HeatmapCanvas'
import { heatmapsBrowserLogic } from 'scenes/heatmaps/components/heatmapsBrowserLogic'

export function FixedReplayHeatmapBrowser({
    iframeRef,
}: {
    iframeRef?: React.MutableRefObject<HTMLIFrameElement | null>
}): JSX.Element | null {
    const logic = heatmapsBrowserLogic()

    const { replayIframeData, hasValidReplayIframeData, widthOverride } = useValues(logic)
    const { onIframeLoad } = useActions(logic)

    return hasValidReplayIframeData ? (
        <div className="flex flex-row gap-x-2 w-full">
            <div className="relative flex-1 w-full h-full">
                <div className="flex justify-center h-full w-full overflow-scroll">
                    <div
                        className="relative h-full overflow-scroll"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: widthOverride }}
                    >
                        <HeatmapCanvas positioning="absolute" widthOverride={widthOverride} context="in-app" />
                        <iframe
                            id="heatmap-iframe"
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
