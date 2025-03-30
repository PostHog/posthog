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
        heatmapEmpty,
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
            <FilterPanel {...fixedReplayFilterPanelProps} isEmpty={heatmapEmpty} />
            <div className="relative flex-1 w-full h-full">
                <HeatmapCanvas positioning="absolute" />
                <iframe
                    ref={iframeRef}
                    className="w-full h-full bg-white"
                    srcDoc={replayIframeData?.html}
                    onLoad={onIframeLoad}
                    allow=""
                />
            </div>
        </div>
    ) : null
}
