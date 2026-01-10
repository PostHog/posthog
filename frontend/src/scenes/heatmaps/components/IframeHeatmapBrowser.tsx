import { useActions, useValues } from 'kea'
import React from 'react'

import { HeatmapCanvas } from 'lib/components/heatmaps/HeatmapCanvas'
import { heatmapsBrowserLogic } from 'scenes/heatmaps/components/heatmapsBrowserLogic'

export function IframeHeatmapBrowser({
    iframeRef,
}: {
    iframeRef?: React.MutableRefObject<HTMLIFrameElement | null>
}): JSX.Element {
    const logic = heatmapsBrowserLogic()

    const { widthOverride, dataUrl, displayUrl } = useValues(logic)
    const { onIframeLoad } = useActions(logic)

    return (
        <div className="flex flex-row gap-x-2 w-full min-h-full">
            <div className="relative flex justify-center flex-1 w-full min-h-full overflow-scroll">
                <div
                    className="relative h-full overflow-scroll"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: widthOverride }}
                >
                    <HeatmapCanvas positioning="absolute" widthOverride={widthOverride} context="in-app" />
                    <iframe
                        id="heatmap-iframe"
                        ref={iframeRef}
                        className="h-full bg-white"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: widthOverride }}
                        src={displayUrl || dataUrl || ''}
                        onLoad={onIframeLoad}
                        // these two sandbox values are necessary so that the site and toolbar can run
                        // this is a very loose sandbox,
                        // but we specify it so that at least other capabilities are denied
                        sandbox="allow-scripts allow-same-origin"
                        // we don't allow things such as camera access though
                        allow=""
                    />
                </div>
            </div>
        </div>
    )
}
