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

    const { replayIframeData, hasValidReplayIframeData, widthOverride, heightOverride } = useValues(logic)
    const { onIframeLoad } = useActions(logic)

    return hasValidReplayIframeData ? (
        <div className="flex flex-row gap-x-2 w-full">
            <div className="relative flex-1 w-full h-full">
                <div className="flex justify-center h-full w-full overflow-auto">
                    <div
                        className="relative"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: widthOverride, height: heightOverride }}
                    >
                        <HeatmapCanvas positioning="absolute" widthOverride={widthOverride} context="in-app" />
                        <iframe
                            id="heatmap-iframe"
                            ref={iframeRef}
                            className="bg-white"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ width: widthOverride, height: heightOverride }}
                            srcDoc={replayIframeData?.html}
                            sandbox=""
                            onLoad={onIframeLoad}
                            allow=""
                        />
                    </div>
                </div>
            </div>
        </div>
    ) : null
}
