import h337, { Heatmap as HeatmapJS } from 'heatmap.js'
import { useValues } from 'kea'
import { useCallback, useEffect, useRef } from 'react'

import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'

export function Heatmap(): JSX.Element | null {
    const { heatmapJsData, heatmapEnabled, heatmapFilters } = useValues(heatmapLogic)
    const h337Ref = useRef<HeatmapJS<'value', 'x', 'y'>>()
    const h337ContainerRef = useRef<HTMLDivElement | null>()

    const updateHeatmapData = useCallback((): void => {
        try {
            h337Ref.current?.setData(heatmapJsData)
        } catch (e) {
            console.error('error setting data', e)
        }
    }, [heatmapJsData])

    const setHeatmapContainer = useCallback((container: HTMLDivElement | null): void => {
        h337ContainerRef.current = container
        if (!container) {
            return
        }

        h337Ref.current = h337.create({
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
        <div className="fixed inset-0 overflow-hidden">
            <div className="absolute inset-0" ref={setHeatmapContainer} />
        </div>
    )
}
