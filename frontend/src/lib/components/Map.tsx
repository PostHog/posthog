import React, { useEffect, useRef } from 'react'
import { Map as RawMap, Marker } from 'maplibre-gl'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'

/** Latitude and longtitude in degrees (+lat is east, -lat is west, +lon is south, -lon is north). */
export interface MapProps {
    /** Coordinates to center the map on by default. */
    center: [number, number]
    /** Markers to show. */
    markers?: Marker[]
    style?: React.CSSProperties
}

export function Map({ center, markers, style }: MapProps): JSX.Element {
    const mapContainer = useRef<HTMLDivElement>(null)
    const map = useRef<RawMap | null>(null)

    useEffect(() => {
        map.current = new RawMap({
            container: mapContainer.current as HTMLElement,
            style: `https://api.maptiler.com/maps/streets-v2/style.json?key=zir7QMNVAfEFm1rVDNV2`,
            center,
            zoom: 9,
            maxZoom: 15,
        })
        if (markers) {
            for (const marker of markers) {
                marker.addTo(map.current)
            }
        }
    }, [])

    useResizeObserver({
        ref: mapContainer,
        onResize: () => {
            if (map.current) {
                map.current.resize()
            }
        },
    })

    return <div ref={mapContainer} style={style} />
}
