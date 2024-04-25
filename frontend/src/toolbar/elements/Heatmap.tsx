import heatmapsJs, { Heatmap as HeatmapJS } from 'heatmap.js'
import { useValues } from 'kea'
import { MutableRefObject, useCallback, useEffect, useRef } from 'react'

import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'

import { useMousePosition } from './useMousePosition'

function HeatmapMouseInfo({
    heatmapJsRef,
}: {
    heatmapJsRef: MutableRefObject<HeatmapJS<'value', 'x', 'y'> | undefined>
}): JSX.Element | null {
    const { shiftPressed, heatmapFilters } = useValues(heatmapLogic)

    const mousePosition = useMousePosition()
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
                className="absolute border rounded bg-bg-light shadow-md p-2 mx-2"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    left: leftPosition ? undefined : 0,
                    right: leftPosition ? 0 : undefined,
                    transform: 'translateY(-50%)',
                }}
            >
                <span className="font-semibold whitespace-nowrap">
                    {value} {heatmapFilters.type + 's'}
                </span>
            </div>
        </div>
    )
}

export function Heatmap(): JSX.Element | null {
    const { heatmapJsData, heatmapEnabled, heatmapFilters, windowWidth, windowHeight } = useValues(heatmapLogic)
    const heatmapsJsRef = useRef<HeatmapJS<'value', 'x', 'y'>>()
    const heatmapsJsContainerRef = useRef<HTMLDivElement | null>()

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
            container,
        })

        updateHeatmapData()
    }, [])

    useEffect(() => {
        updateHeatmapData()
    }, [heatmapJsData])

    if (!heatmapEnabled || !heatmapFilters.enabled || heatmapFilters.type === 'scrolldepth') {
        return null
    }

    return (
        <div className="fixed inset-0 overflow-hidden w-full h-full">
            {/* NOTE: We key on the window dimensions which triggers a recreation of the canvas */}
            <div key={`${windowWidth}x${windowHeight}`} className="absolute inset-0" ref={setHeatmapContainer} />
            <HeatmapMouseInfo heatmapJsRef={heatmapsJsRef} />
        </div>
    )
}
