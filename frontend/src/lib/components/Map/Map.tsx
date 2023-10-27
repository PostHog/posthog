import { useEffect, useRef } from 'react'
import { Map as RawMap, Marker, StyleSpecification } from 'maplibre-gl'
import layers from 'protomaps-themes-base'
import useResizeObserver from 'use-resize-observer'
import { useValues } from 'kea'

import 'maplibre-gl/dist/maplibre-gl.css'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

// :TRICKY: The URL absolutely needs to be prefixed with `pmtiles://` to work!
const PMTILES_URL = 'pmtiles://https://posthog-prod-maps.s3.us-east-1.amazonaws.com/20230913.pmtiles'

/** Latitude and longtitude in degrees (+lat is east, -lat is west, +lon is south, -lon is north). */
export interface MapProps {
    /** Coordinates to center the map on by default. */
    center: [number, number]
    /** Markers to show. */
    markers?: Marker[]
    /** Map container class names. */
    className?: string
}

export function Map({ center, markers, className }: MapProps): JSX.Element {
    const mapContainer = useRef<HTMLDivElement>(null)
    const map = useRef<RawMap | null>(null)
    const { isDarkModeOn } = useValues(themeLogic)
    const { isCloudOrDev } = useValues(preflightLogic)

    if (!isCloudOrDev) {
        return (
            <div className={`w-full h-full flex flex-col items-center justify-center text-muted p-3 ${className}`}>
                <h1>Map unavailable</h1>
                <p>The map is currently only available in cloud deployments.</p>
            </div>
        )
    }

    useEffect(() => {
        map.current = new RawMap({
            container: mapContainer.current as HTMLElement,
            style: {
                version: 8,
                glyphs: 'https://cdn.protomaps.com/fonts/pbf/{fontstack}/{range}.pbf',
                sources: {
                    protomaps: {
                        type: 'vector',
                        url: PMTILES_URL,
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
