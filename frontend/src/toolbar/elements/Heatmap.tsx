import h337 from 'heatmap.js'
import { useValues } from 'kea'
import { useCallback, useEffect, useRef } from 'react'

import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'

export function Heatmap(): JSX.Element | null {
    const { heatmapElements, heatmapEnabled, heatmapFilters } = useValues(heatmapLogic)
    const h337Ref = useRef<any>()
    const h337ContainerRef = useRef<HTMLDivElement | null>()

    const updateHeatmapData = (): void => {
        try {
            h337Ref.current?.setData({
                max: heatmapElements.reduce((max, { count }) => Math.max(max, count), 0),
                data: heatmapElements.map(({ xPercentage, y, count }) => ({
                    x: xPercentage * (h337ContainerRef.current?.offsetWidth ?? window.innerWidth),
                    y: y,
                    value: count,
                    // targetFixed,
                })),
            })
        } catch (e) {
            console.error('error setting data', e)
        }
    }

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
    }, [heatmapElements])

    if (!heatmapEnabled || !heatmapFilters.enabled || heatmapFilters.type === 'scrolldepth') {
        return null
    }

    return (
        <div className="fixed inset-0 overflow-hidden">
            <div className="absolute inset-0" ref={setHeatmapContainer} />
        </div>
    )
}
