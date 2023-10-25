import { useEffect, useRef } from 'react'
import { Map as RawMap, Marker, StyleSpecification } from 'maplibre-gl'
import layers from 'protomaps-themes-base'
import useResizeObserver from 'use-resize-observer'
import { useValues } from 'kea'

import 'maplibre-gl/dist/maplibre-gl.css'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

/** Latitude and longtitude in degrees (+lat is east, -lat is west, +lon is south, -lon is north). */
export interface MapProps {
    /** Coordinates to center the map on by default. */
    center: [number, number]
    /** Markers to show. */
    markers?: Marker[]
    /** Map container class names. */
    className?: string
    /** The map's MapLibre style. This must be a JSON object conforming to the schema described in the MapLibre Style Specification, or a URL to such JSON. */
    mapLibreStyleUrl: string | StyleSpecification
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
    const { isDarkModeOn } = useValues(themeLogic)

    useEffect(() => {
        map.current = new RawMap({
            container: mapContainer.current as HTMLElement,
            style: {
                version: 8,
                glyphs: 'https://cdn.protomaps.com/fonts/pbf/{fontstack}/{range}.pbf',
                sources: {
                    protomaps: {
                        type: 'vector',
                        // tiles: ['https://api.protomaps.com/tiles/v3/{z}/{x}/{y}.mvt?key=KEY'],
                        // url: 'pmtiles://https://example.com/example.pmtiles',
                        url: 'pmtiles://http://127.0.0.1:8080/20230913.pmtiles',
                        attribution:
                            '<a href="https://protomaps.com">Protomaps</a> © <a href="https://openstreetmap.org">OpenStreetMap</a>',
                    },
                },
                layers: layers('protomaps', isDarkModeOn ? 'dark' : 'light'),
            },
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
