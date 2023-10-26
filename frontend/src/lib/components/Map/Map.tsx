import { useEffect, useRef } from 'react'
import { Map as RawMap, Marker } from 'maplibre-gl'
import useResizeObserver from 'use-resize-observer'

import 'maplibre-gl/dist/maplibre-gl.css'

/** Latitude and longtitude in degrees (+lat is east, -lat is west, +lon is south, -lon is north). */
export interface MapProps {
    /** Coordinates to center the map on by default. */
    center: [number, number]
    /** Markers to show. */
    markers?: Marker[]
    /** Map container class names. */
    className?: string
    /** The map's MapLibre style. This must be a JSON object conforming to the schema described in the MapLibre Style Specification, or a URL to such JSON. */
    mapLibreStyleUrl: string
}

export function Map({ className, ...rest }: Omit<MapProps, 'mapLibreStyleUrl'>): JSX.Element {
    if (!window.JS_MAPLIBRE_STYLE_URL) {
        return (
            <div className={`w-full h-full flex flex-col items-center justify-center text-muted p-3 ${className}`}>
                <h1>Map unavailable</h1>
                <p>
                    The <code>MAPLIBRE_STYLE_URL</code> setting is not defined. Please configure this setting with a
                    valid MapLibre Style URL to display maps.
                </p>
            </div>
        )
    }

    return <MapComponent mapLibreStyleUrl={window.JS_MAPLIBRE_STYLE_URL} className={className} {...rest} />
}

export function MapComponent({ center, markers, className, mapLibreStyleUrl }: MapProps): JSX.Element {
    const mapContainer = useRef<HTMLDivElement>(null)
    const map = useRef<RawMap | null>(null)

    useEffect(() => {
        map.current = new RawMap({
            container: mapContainer.current as HTMLElement,
            style: mapLibreStyleUrl,
            center,
            zoom: 4,
            maxZoom: 10,
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

    return <div ref={mapContainer} className={className} />
}
