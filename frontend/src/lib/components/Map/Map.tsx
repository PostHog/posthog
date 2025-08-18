import './Maplibre.scss'
import 'maplibre-gl/dist/maplibre-gl.css'

import { useValues } from 'kea'
import maplibregl, { Marker, Map as RawMap } from 'maplibre-gl'
import { Protocol } from 'pmtiles'
import layers from 'protomaps-themes-base'
import { useEffect, useRef } from 'react'
import useResizeObserver from 'use-resize-observer'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

const protocol = new Protocol()
maplibregl.addProtocol('pmtiles', protocol.tile)

const BASE_URL = 'https://posthog-prod-maps.s3.us-east-1.amazonaws.com'
// :TRICKY: The URL absolutely needs to be prefixed with `pmtiles://` to work!
const PMTILES_URL = `pmtiles://${BASE_URL}/20230913.pmtiles`
const GLYPH_URL = `${BASE_URL}/fonts/pbf/{fontstack}/{range}.pbf`

/** Latitude and longtitude in degrees (+lat is east, -lat is west, +lon is south, -lon is north). */
export interface MapProps {
    /** Coordinates to center the map on by default. */
    center: [number, number]
    /** Markers to show. */
    markers?: Marker[]
    /** Map container class names. */
    className?: string
}

export function Map({ className, ...rest }: MapProps): JSX.Element {
    const { isCloudOrDev } = useValues(preflightLogic)

    if (!isCloudOrDev) {
        return (
            <div className={`w-full h-full flex flex-col items-center justify-center text-secondary p-3 ${className}`}>
                <h1>Map unavailable</h1>
                <p>The map is currently only available in cloud deployments.</p>
            </div>
        )
    }

    return <MapComponent className={className} {...rest} />
}

export function MapComponent({ center, markers, className }: MapProps): JSX.Element {
    const mapContainer = useRef<HTMLDivElement>(null)
    const map = useRef<RawMap | null>(null)

    const { isDarkModeOn } = useValues(themeLogic)

    useEffect(() => {
        map.current = new RawMap({
            container: mapContainer.current as HTMLElement,
            style: {
                version: 8,
                glyphs: GLYPH_URL,
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
    }, [isDarkModeOn]) // oxlint-disable-line react-hooks/exhaustive-deps

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
