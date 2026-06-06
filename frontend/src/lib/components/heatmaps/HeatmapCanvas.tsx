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
import { useScrollSync } from './useScrollSync'

// Radius in pixels to search for nearby heatmap elements when clicking
const CLICK_RADIUS_PX = 15

const TOOLTIP_OFFSET_PX = 12
const TOOLTIP_FLIP_THRESHOLD_PX = 160

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
    const { heatmapTooltipLabel, rawHeatmapLoading } = useValues(heatmapDataLogic({ context }))

    const containerMousePosition = useMousePosition(containerRef?.current)
    const viewportMousePosition = useMousePosition()
    const value = heatmapJsRef.current?.getValueAt(containerMousePosition)

    const hasValue = !!(containerMousePosition && (value || shiftPressed))

    useEffect(() => {
        onHasValue?.(hasValue)
    }, [hasValue, onHasValue])

    if (!hasValue) {
        return null
    }

    const flipLeft = window.innerWidth - viewportMousePosition.x < TOOLTIP_FLIP_THRESHOLD_PX

    return (
        <div
            className="fixed z-10 -translate-y-1/2 pointer-events-none"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                top: viewportMousePosition.y,
                left: flipLeft ? undefined : viewportMousePosition.x + TOOLTIP_OFFSET_PX,
                right: flipLeft ? window.innerWidth - viewportMousePosition.x + TOOLTIP_OFFSET_PX : undefined,
            }}
        >
            <div className="border rounded bg-surface-primary shadow-md p-2 whitespace-nowrap font-semibold">
                {rawHeatmapLoading ? 'Loading…' : `${value ?? 0} ${heatmapTooltipLabel}`}
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
        windowWidthOverride,
    } = useValues(heatmapDataLogic({ context, exportToken }))
    const { setSelectedArea } = useActions(heatmapDataLogic({ context, exportToken }))

    const heatmapsJsRef = useRef<HeatmapJS<'value', 'x', 'y'>>()
    const heatmapsJsContainerRef = useRef<HTMLDivElement | null>()
    const isToolbar = context === 'toolbar'
    const { innerRef, scrollYRef } = useScrollSync(isToolbar)
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

    const heatmapJsDataRef = useRef(heatmapJsData)
    heatmapJsDataRef.current = heatmapJsData
    const heatmapJSColorGradientRef = useRef(heatmapJSColorGradient)
    heatmapJSColorGradientRef.current = heatmapJSColorGradient

    const handleCanvasClick = useCallback(
        (e: React.MouseEvent<HTMLDivElement>): void => {
            const rect = e.currentTarget.getBoundingClientRect()
            const clickX = e.clientX - rect.left
            const clickY = isToolbar ? e.clientY - rect.top + scrollYRef.current : e.clientY - rect.top

            const width = windowWidthOverride ?? windowWidth

            // Find all elements within CLICK_RADIUS_PX of the click
            const nearbyElements: HeatmapAreaPoint[] = []
            let totalCount = 0

            for (const element of heatmapElements) {
                const visualX = element.xPercentage * width
                const distance = Math.sqrt(Math.pow(clickX - visualX, 2) + Math.pow(clickY - element.y, 2))

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
        [heatmapElements, windowWidth, windowWidthOverride, setSelectedArea, isToolbar, scrollYRef]
    )

    const setHeatmapContainer = useCallback((container: HTMLDivElement | null): void => {
        heatmapsJsContainerRef.current = container
        if (!container) {
            return
        }

        heatmapsJsRef.current = heatmapsJs.create({
            ...HEATMAP_CONFIG,
            container,
            gradient: heatmapJSColorGradientRef.current,
        })

        try {
            heatmapsJsRef.current.setData(heatmapJsDataRef.current)
        } catch (e) {
            console.error('error setting data', e)
        }
    }, [])

    useEffect(() => {
        try {
            heatmapsJsRef.current?.setData(heatmapJsData)
        } catch (e) {
            console.error('error setting data', e)
        }
    }, [heatmapJsData])

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

    const loadingClass = isReady
        ? 'heatmaps-ready opacity-100 transition-opacity duration-150'
        : 'heatmaps-loading opacity-40 pointer-events-none transition-opacity duration-150'

    if (isToolbar) {
        return (
            <div
                className={cn('fixed inset-0 overflow-hidden', hasValueUnderMouse && 'cursor-pointer')}
                data-attr="heatmap-canvas"
                onClick={handleCanvasClick}
            >
                <div
                    ref={innerRef}
                    className={cn('absolute top-0 left-0 w-full', loadingClass)}
                    style={{ height: heightOverride, willChange: 'transform' }}
                >
                    <div
                        key={`${widthOverride ?? windowWidth}x${heightOverride}x${heatmapFixedPositionMode}`}
                        className="absolute top-0 left-0 w-full h-full"
                        ref={setHeatmapContainer}
                    />
                </div>
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

    return (
        <div
            className={cn('inset-0 overflow-hidden w-full h-full', positioning, hasValueUnderMouse && 'cursor-pointer')}
            data-attr="heatmap-canvas"
            onClick={handleCanvasClick}
        >
            <div
                key={
                    exportToken
                        ? 'export-heatmap'
                        : `${widthOverride ?? windowWidth}x${windowHeight}x${heightOverride}x${heatmapFixedPositionMode}`
                }
                className={cn('absolute inset-0', loadingClass)}
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
