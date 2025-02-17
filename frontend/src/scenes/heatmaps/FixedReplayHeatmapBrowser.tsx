import { useActions, useValues } from 'kea'
import { HeatmapCanvas } from 'lib/components/heatmaps/HeatmapCanvas'
import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import React, { useEffect } from 'react'
import { FilterPanel } from 'scenes/heatmaps/FilterPanel'
import { heatmapsBrowserLogic } from 'scenes/heatmaps/heatmapsBrowserLogic'

export function FixedReplayHeatmapBrowser({
    iframeRef,
}: {
    iframeRef?: React.MutableRefObject<HTMLIFrameElement | null>
}): JSX.Element | null {
    const logic = heatmapsBrowserLogic()

    const { replayIframeData, hasValidReplayIframeData, filterPanelCollapsed } = useValues(logic)
    const { onIframeLoad, setIframeWidth, toggleFilterPanelCollapsed } = useActions(logic)

    const {
        heatmapFilters,
        heatmapColorPalette,
        heatmapFixedPositionMode,
        viewportRange,
        commonFilters,
        rawHeatmapLoading,
    } = useValues(heatmapDataLogic)
    const { patchHeatmapFilters, setHeatmapColorPalette, setHeatmapFixedPositionMode, setCommonFilters } =
        useActions(heatmapDataLogic)

    const fixedReplayFilterPanelProps = {
        heatmapFilters,
        heatmapColorPalette,
        heatmapFixedPositionMode,
        viewportRange,
        commonFilters,
        filterPanelCollapsed,
        loading: rawHeatmapLoading,
        patchHeatmapFilters,
        setHeatmapColorPalette,
        setHeatmapFixedPositionMode,
        setCommonFilters,
        toggleFilterPanelCollapsed,
    }

    const { width: iframeWidth } = useResizeObserver<HTMLIFrameElement>({ ref: iframeRef })
    useEffect(() => {
        setIframeWidth(iframeWidth ?? null)
    }, [iframeWidth])

    return hasValidReplayIframeData ? (
        <div className="flex flex-row gap-x-2 w-full">
            <FilterPanel {...fixedReplayFilterPanelProps} />
            <div className="relative flex-1 w-full h-full">
                {/*{loading ? <LoadingOverlay /> : null}*/}
                {/*{!loading && iframeBanner ? <IframeErrorOverlay /> : null}*/}
                <HeatmapCanvas positioning="absolute" />
                <iframe
                    ref={iframeRef}
                    className="w-full h-full bg-white"
                    // src={appEditorUrl(browserUrl, {
                    //     userIntent: 'heatmaps',
                    // })}
                    srcDoc={replayIframeData?.html}
                    onLoad={onIframeLoad}
                    // these two sandbox values are necessary so that the site and toolbar can run
                    // this is a very loose sandbox,
                    // but we specify it so that at least other capabilities are denied
                    // sandbox="allow-scripts allow-same-origin"
                    // we don't allow things such as camera access though
                    allow=""
                />
            </div>
        </div>
    ) : null
}
