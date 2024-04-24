import heatmapsJs, { Heatmap as HeatmapJS } from 'heatmap.js'
import { useValues } from 'kea'
import { useCallback, useEffect, useRef } from 'react'

import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'

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
        </div>
    )
}
