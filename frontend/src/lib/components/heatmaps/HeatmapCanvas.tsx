import heatmapsJs, { Heatmap as HeatmapJS } from 'heatmap.js'
import { useValues } from 'kea'
import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { useShiftKeyPressed } from 'lib/components/heatmaps/useShiftKeyPressed'
import { cn } from 'lib/utils/css-classes'
import { MutableRefObject, useCallback, useEffect, useMemo, useRef } from 'react'

import { useMousePosition } from './useMousePosition'

function HeatmapMouseInfo({
    heatmapJsRef,
    containerRef,
    context,
}: {
    heatmapJsRef: MutableRefObject<HeatmapJS<'value', 'x', 'y'> | undefined>
    containerRef: MutableRefObject<HTMLDivElement | null | undefined>
    context: 'in-app' | 'toolbar'
}): JSX.Element | null {
    const shiftPressed = useShiftKeyPressed()
    const { heatmapTooltipLabel } = useValues(heatmapDataLogic({ context }))

    const mousePosition = useMousePosition(containerRef?.current)
    const value = heatmapJsRef.current?.getValueAt(mousePosition)

    if (!mousePosition || (!value && !shiftPressed)) {
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
}: {
    positioning?: 'absolute' | 'fixed'
    widthOverride?: number | null
    context: 'in-app' | 'toolbar'
}): JSX.Element | null {
    const { heatmapJsData, heatmapFilters, windowWidth, windowHeight, heatmapColorPalette } = useValues(
        heatmapDataLogic({ context })
    )

    const heatmapsJsRef = useRef<HeatmapJS<'value', 'x', 'y'>>()
    const heatmapsJsContainerRef = useRef<HTMLDivElement | null>()

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

    const heatmapConfig = {
        minOpacity: 0,
        maxOpacity: 0.8,
    }

    const updateHeatmapData = useCallback((): void => {
        try {
            heatmapsJsRef.current?.setData(heatmapJsData)
        } catch (e) {
            console.error('error setting data', e)
        }
    }, [heatmapJsData])

    const setHeatmapContainer = useCallback((container: HTMLDivElement | null): void => {
        heatmapsJsContainerRef.current = container
        if (!container) {
            return
        }

        heatmapsJsRef.current = heatmapsJs.create({
            ...heatmapConfig,
            container,
            gradient: heatmapJSColorGradient,
        })

        updateHeatmapData()
    }, [])

    useEffect(() => {
        updateHeatmapData()
    }, [heatmapJsData])

    useEffect(() => {
        if (!heatmapsJsContainerRef.current) {
            return
        }

        heatmapsJsRef.current?.configure({
            ...heatmapConfig,
            container: heatmapsJsContainerRef.current,
            gradient: heatmapJSColorGradient,
        })
    }, [heatmapJSColorGradient])

    if (!heatmapFilters.enabled || heatmapFilters.type === 'scrolldepth') {
        return null
    }

    return (
        <div className={cn('inset-0 overflow-hidden w-full h-full', positioning)} data-attr="heatmap-canvas">
            {/* NOTE: We key on the window dimensions which triggers a recreation of the canvas */}
            <div
                key={`${widthOverride ?? windowWidth}x${windowHeight}`}
                className="absolute inset-0"
                ref={setHeatmapContainer}
            />
            <HeatmapMouseInfo heatmapJsRef={heatmapsJsRef} containerRef={heatmapsJsContainerRef} context={context} />
        </div>
    )
}
