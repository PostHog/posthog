import { useActions, useValues } from 'kea'
import React from 'react'

import { HeatmapCanvas } from 'lib/components/heatmaps/HeatmapCanvas'
import { heatmapsBrowserLogic } from 'scenes/heatmaps/components/heatmapsBrowserLogic'
import { RecordingClickmapOverlay } from 'scenes/heatmaps/components/RecordingClickmapOverlay'

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
                        <RecordingClickmapOverlay iframeRef={iframeRef} />
                        <iframe
                            id="heatmap-iframe"
                            ref={iframeRef}
                            title="Heatmap replay browser"
                            className="bg-white"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ width: widthOverride, height: heightOverride }}
                            srcDoc={replayIframeData?.html}
                            // allow-same-origin (without allow-scripts, so the snapshot stays inert)
                            // lets the app measure the snapshot's elements for the clickmap overlay
                            sandbox="allow-same-origin"
                            onLoad={onIframeLoad}
                            allow=""
                        />
                    </div>
                </div>
            </div>
        </div>
    ) : null
}
