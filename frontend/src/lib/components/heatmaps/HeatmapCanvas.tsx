import heatmapsJs, { Heatmap as HeatmapJS } from 'heatmap.js'
import { useActions, useValues } from 'kea'
import { MutableRefObject, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { HeatmapAreaPoint } from 'lib/components/heatmaps/types'
import { useShiftKeyPressed } from 'lib/components/heatmaps/useShiftKeyPressed'
import { cn } from 'lib/utils/css-classes'

import { HeatmapEventsPanel } from './HeatmapEventsPanel'
import { ScrollDepthCanvas } from './ScrollDepthCanvas'
import { useMousePosition } from './useMousePosition'

// Radius in pixels to search for nearby heatmap elements when clicking
const CLICK_RADIUS_PX = 15

const HEATMAP_CONFIG = {
    minOpacity: 0,
    maxOpacity: 0.8,
}

function HeatmapMouseInfo({
    heatmapJsRef,
    containerRef,
    context,
    onHasValue,
}: {
    heatmapJsRef: MutableRefObject<HeatmapJS<'value', 'x', 'y'> | undefined>
    containerRef: MutableRefObject<HTMLDivElement | null | undefined>
    context: 'in-app' | 'toolbar'
    onHasValue?: (hasValue: boolean) => void
}): JSX.Element | null {
    const shiftPressed = useShiftKeyPressed()
    const { heatmapTooltipLabel } = useValues(heatmapDataLogic({ context }))

    const mousePosition = useMousePosition(containerRef?.current)
    const value = heatmapJsRef.current?.getValueAt(mousePosition)

    const hasValue = !!(mousePosition && (value || shiftPressed))

    useEffect(() => {
        onHasValue?.(hasValue)
    }, [hasValue, onHasValue])

    if (!hasValue) {
        return null
    }

    const leftPosition = window.innerWidth - mousePosition.x < 100

    return (
        <div
            className="absolute z-10"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                top: mousePosition.y,
                left: mousePosition.x,
            }}
        >
            <div
                className="absolute border rounded bg-surface-primary shadow-md p-2 mx-2 -translate-y-1/2"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    left: leftPosition ? undefined : 0,
                    right: leftPosition ? 0 : undefined,
                }}
            >
                <span className="font-semibold whitespace-nowrap">
                    {value} {heatmapTooltipLabel}
                </span>
            </div>
        </div>
    )
}

export function HeatmapCanvas({
    positioning = 'fixed',
    widthOverride,
    context,
    exportToken,
}: {
    positioning?: 'absolute' | 'fixed'
    widthOverride?: number | null
    context: 'in-app' | 'toolbar'
    exportToken?: string
}): JSX.Element | null {
    const {
        heatmapJsData,
        heatmapFilters,
        windowWidth,
        windowHeight,
        heatmapColorPalette,
        isReady,
        heightOverride,
        heatmapFixedPositionMode,
        heatmapElements,
        heatmapScrollY,
        windowWidthOverride,
    } = useValues(heatmapDataLogic({ context, exportToken }))
    const { setSelectedArea } = useActions(heatmapDataLogic({ context, exportToken }))

    const heatmapsJsRef = useRef<HeatmapJS<'value', 'x', 'y'>>()
    const heatmapsJsContainerRef = useRef<HTMLDivElement | null>()
    const [hasValueUnderMouse, setHasValueUnderMouse] = useState(false)

    const heatmapJSColorGradient = useMemo((): Record<string, string> => {
        switch (heatmapColorPalette) {
            case 'blue':
                return { '.0': 'rgba(0, 0, 255, 0)', '.100': 'rgba(0, 0, 255, 1)' }
            case 'green':
                return { '.0': 'rgba(0, 255, 0, 0)', '.100': 'rgba(0, 255, 0, 1)' }
            case 'red':
                return { '.0': 'rgba(255, 0, 0, 0)', '.100': 'rgba(255, 0, 0, 1)' }

            default:
                // Defaults taken from heatmap.js
                return { '.25': 'rgb(0,0,255)', '0.55': 'rgb(0,255,0)', '0.85': 'yellow', '1.0': 'rgb(255,0,0)' }
        }
    }, [heatmapColorPalette])

    const handleCanvasClick = useCallback(
        (e: React.MouseEvent<HTMLDivElement>): void => {
            const rect = e.currentTarget.getBoundingClientRect()
            const clickX = e.clientX - rect.left
            const clickY = e.clientY - rect.top

            const width = windowWidthOverride ?? windowWidth

            // Find all elements within CLICK_RADIUS_PX of the click
            const nearbyElements: HeatmapAreaPoint[] = []
            let totalCount = 0

            for (const element of heatmapElements) {
                // Calculate visual position (same logic as heatmapJsData selector)
                const visualY =
                    element.targetFixed && heatmapFixedPositionMode === 'fixed' ? element.y : element.y - heatmapScrollY
                const visualX = element.xPercentage * width

                const distance = Math.sqrt(Math.pow(clickX - visualX, 2) + Math.pow(clickY - visualY, 2))

                if (distance <= CLICK_RADIUS_PX) {
                    nearbyElements.push({
                        x: element.xPercentage,
                        y: element.y,
                        target_fixed: element.targetFixed,
                    })
                    totalCount += element.count
                }
            }

            if (nearbyElements.length > 0) {
                setSelectedArea({
                    points: nearbyElements,
                    expectedCount: totalCount,
                    clickX,
                    clickY,
                })
            }
        },
        [heatmapElements, heatmapScrollY, windowWidth, windowWidthOverride, heatmapFixedPositionMode, setSelectedArea]
    )

    const updateHeatmapData = useCallback((): void => {
        try {
            heatmapsJsRef.current?.setData(heatmapJsData)
        } catch (e) {
            console.error('error setting data', e)
        }
    }, [heatmapJsData])

    const setHeatmapContainer = useCallback(
        (container: HTMLDivElement | null): void => {
            heatmapsJsContainerRef.current = container
            if (!container) {
                return
            }

            heatmapsJsRef.current = heatmapsJs.create({
                ...HEATMAP_CONFIG,
                container,
                gradient: heatmapJSColorGradient,
            })

            updateHeatmapData()
        },
        [updateHeatmapData, heatmapJSColorGradient] // oxlint-disable-line react-hooks/exhaustive-deps
    )

    useEffect(() => {
        updateHeatmapData()
    }, [heatmapJsData]) // oxlint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        if (!heatmapsJsContainerRef.current) {
            return
        }

        heatmapsJsRef.current?.configure({
            ...HEATMAP_CONFIG,
            container: heatmapsJsContainerRef.current,
            gradient: heatmapJSColorGradient,
        })
    }, [heatmapJSColorGradient])

    if (!heatmapFilters.enabled) {
        return null
    }

    if (heatmapFilters.type === 'scrolldepth') {
        return (
            <ScrollDepthCanvas
                key={`scrolldepth-${heatmapFilters.type}-${exportToken ? 'export' : `${widthOverride ?? windowWidth}x${windowHeight}`}`}
                positioning={positioning}
                context={context}
                exportToken={exportToken}
            />
        )
    }

    return (
        <div
            className={cn(
                'inset-0 overflow-hidden w-full h-full',
                positioning,
                isReady ? 'heatmaps-ready' : 'heatmaps-loading',
                hasValueUnderMouse && 'cursor-pointer'
            )}
            data-attr="heatmap-canvas"
            onClick={handleCanvasClick}
        >
            {/* NOTE: We key on the window dimensions and fixed position mode which triggers a recreation of the canvas */}
            <div
                key={
                    exportToken
                        ? 'export-heatmap'
                        : `${widthOverride ?? windowWidth}x${windowHeight}x${heightOverride}x${heatmapFixedPositionMode}`
                }
                className="absolute inset-0"
                ref={setHeatmapContainer}
            />
            <HeatmapMouseInfo
                heatmapJsRef={heatmapsJsRef}
                containerRef={heatmapsJsContainerRef}
                context={context}
                onHasValue={setHasValueUnderMouse}
            />
            <HeatmapEventsPanel context={context} exportToken={exportToken} />
        </div>
    )
}
