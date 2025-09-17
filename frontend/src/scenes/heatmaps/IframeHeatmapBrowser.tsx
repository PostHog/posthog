import { useActions, useValues } from 'kea'
import React, { useEffect } from 'react'

import { IconDownload } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { HeatmapCanvas } from 'lib/components/heatmaps/HeatmapCanvas'
import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FilterPanel } from 'scenes/heatmaps/FilterPanel'
import { heatmapsBrowserLogic } from 'scenes/heatmaps/heatmapsBrowserLogic'

import { ViewportChooser } from './HeatmapsBrowser'

export function IframeHeatmapBrowser({
    iframeRef,
}: {
    iframeRef?: React.MutableRefObject<HTMLIFrameElement | null>
}): JSX.Element {
    const logic = heatmapsBrowserLogic()

    const { filterPanelCollapsed, widthOverride, browserUrl } = useValues(logic)
    const { onIframeLoad, setIframeWidth, toggleFilterPanelCollapsed } = useActions(logic)
    const { startHeatmapExport } = useActions(exportsLogic)

    const {
        heatmapFilters,
        heatmapColorPalette,
        heatmapFixedPositionMode,
        viewportRange,
        commonFilters,
        rawHeatmapLoading,
        heatmapEmpty,
    } = useValues(heatmapDataLogic({ context: 'in-app' }))
    const {
        patchHeatmapFilters,
        setHeatmapColorPalette,
        setHeatmapFixedPositionMode,
        setCommonFilters,
        setWindowWidthOverride,
    } = useActions(heatmapDataLogic({ context: 'in-app' }))

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

    const { featureFlags } = useValues(featureFlagLogic)

    const { width: iframeWidth, height: iframeHeight } = useResizeObserver<HTMLIFrameElement>({ ref: iframeRef })
    useEffect(() => {
        if (widthOverride === null) {
            setIframeWidth(iframeWidth ?? null)
        }
        setWindowWidthOverride(widthOverride)
    }, [iframeWidth, setIframeWidth, widthOverride, setWindowWidthOverride])

    const handleExport = (): void => {
        if (browserUrl) {
            startHeatmapExport({
                heatmap_url: browserUrl,
                width: iframeWidth,
                height: iframeHeight,
                heatmap_color_palette: heatmapColorPalette,
                heatmap_fixed_position_mode: heatmapFixedPositionMode,
                common_filters: commonFilters,
                heatmap_filters: heatmapFilters,
                filename: `heatmap-${new URL(browserUrl).hostname}/${new URL(browserUrl).pathname.slice(1, 11)}-${dayjs().format('YYYY-MM-DD-HH-mm')}`,
            })
        }
    }

    return (
        <div className="flex flex-row gap-x-2 w-full">
            <FilterPanel {...fixedReplayFilterPanelProps} isEmpty={heatmapEmpty} />
            <div className="relative flex-1 w-full h-full mt-2">
                {featureFlags[FEATURE_FLAGS.SCREENSHOT_EDITOR] ? (
                    <>
                        <div className="flex justify-between items-center">
                            <ViewportChooser />
                            <LemonButton
                                className="mb-2 mr-2"
                                type="secondary"
                                onClick={handleExport}
                                icon={<IconDownload />}
                                tooltip="Export heatmap as PNG"
                                data-attr="export-heatmap"
                                disabledReason={!browserUrl ? 'We can export only the URL with heatmaps' : undefined}
                            >
                                <div className="flex w-full gap-x-2 justify-between items-center">
                                    Export{' '}
                                    <LemonTag type="warning" size="small">
                                        BETA
                                    </LemonTag>
                                </div>
                            </LemonButton>
                        </div>
                    </>
                ) : (
                    <ViewportChooser />
                )}
                <div className="flex justify-center h-full w-full overflow-scroll">
                    <div
                        className="relative h-full overflow-scroll"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: widthOverride ?? '100%' }}
                    >
                        <HeatmapCanvas positioning="absolute" widthOverride={widthOverride} context="in-app" />
                        <iframe
                            id="heatmap-iframe"
                            ref={iframeRef}
                            className="h-full bg-white"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ width: widthOverride ?? '100%' }}
                            src={browserUrl ?? ''}
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
        </div>
    )
}
