import { IconLlmPromptEvaluation } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { HeatmapCanvas } from 'lib/components/heatmaps/HeatmapCanvas'
import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { ScreenShotEditor } from 'lib/components/TakeScreenshot/ScreenShotEditor'
import { takeScreenshotLogic } from 'lib/components/TakeScreenshot/takeScreenshotLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import React, { useEffect } from 'react'
import { FilterPanel } from 'scenes/heatmaps/FilterPanel'
import { heatmapsBrowserLogic } from 'scenes/heatmaps/heatmapsBrowserLogic'

import { ViewportChooser } from './HeatmapsBrowser'

export function FixedReplayHeatmapBrowser({
    iframeRef,
}: {
    iframeRef?: React.MutableRefObject<HTMLIFrameElement | null>
}): JSX.Element | null {
    const logic = heatmapsBrowserLogic()

    const { replayIframeData, hasValidReplayIframeData, filterPanelCollapsed, widthOverride } = useValues(logic)
    const { onIframeLoad, setIframeWidth, toggleFilterPanelCollapsed } = useActions(logic)

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
    const { setHtml } = useActions(takeScreenshotLogic({ screenshotKey: 'heatmaps' }))

    const { width: iframeWidth } = useResizeObserver<HTMLIFrameElement>({ ref: iframeRef })
    useEffect(() => {
        if (widthOverride === null) {
            setIframeWidth(iframeWidth ?? null)
        }
        setWindowWidthOverride(widthOverride)
    }, [iframeWidth, setIframeWidth, widthOverride, setWindowWidthOverride])

    const handleShare = (): void => {
        const iframe = iframeRef?.current
        if (!iframe) {
            lemonToast.error('Cannot take screenshot. Please try again.')
            return
        }
        setHtml(iframe)
    }

    return hasValidReplayIframeData ? (
        <div className="flex flex-row gap-x-2 w-full">
            <FilterPanel {...fixedReplayFilterPanelProps} isEmpty={heatmapEmpty} />
            <div className="relative flex-1 w-full h-full mt-2">
                {featureFlags[FEATURE_FLAGS.SCREENSHOT_EDITOR] ? (
                    <>
                        <ScreenShotEditor screenshotKey="heatmaps" />
                        <div className="flex justify-between items-center">
                            <ViewportChooser />
                            <LemonButton
                                className="mb-2 mr-2"
                                type="secondary"
                                onClick={handleShare}
                                icon={<IconLlmPromptEvaluation />}
                            >
                                Take screenshot
                            </LemonButton>
                        </div>
                    </>
                ) : (
                    <ViewportChooser />
                )}
                <div className="flex justify-center h-full w-full">
                    <div
                        className="relative h-full "
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
