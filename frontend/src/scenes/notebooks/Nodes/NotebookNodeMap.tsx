import React, { useEffect, useRef } from 'react'
import { Map as RawMap, Marker } from 'maplibre-gl'

import 'maplibre-gl/dist/maplibre-gl.css'

import { NotebookNodeType } from '~/types'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { NotebookNodeProps } from '../Notebook/utils'

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

    // eslint-disable-next-line react/forbid-dom-props
    return <div ref={mapContainer} style={style} />
}

const Component = ({ attributes, updateAttributes }: NotebookNodeProps<NotebookNodeMapAttributes>): JSX.Element => {
    const { nodeId } = attributes

    const person = {
        properties: {
            $geoip_city_name: 'Modena',
            $geoip_continent_code: 'EU',
            $geoip_continent_name: 'Europe',
            $geoip_country_code: 'IT',
            $geoip_country_name: 'Italy',
            $geoip_latitude: 44.6511,
            $geoip_longitude: 10.9211,
            $geoip_postal_code: '41124',
            $geoip_subdivision_1_code: '45',
            $geoip_subdivision_1_name: 'Emilia-Romagna',
            $geoip_subdivision_2_code: 'MO',
            $geoip_subdivision_2_name: 'Province of Modena',
            $geoip_time_zone: 'Europe/Rome',
        },
    }

    const longtitude = person?.properties?.['$geoip_longitude']
    const latitude = person?.properties?.['$geoip_latitude']
    const personCoordinates: [number, number] | null =
        !isNaN(longtitude) && !isNaN(latitude) ? [longtitude, latitude] : null

    if (!personCoordinates) {
        return (
            <span>
                <i>No Map available.</i>
            </span>
        )
    }

    return (
        <Map
            center={personCoordinates}
            markers={[new Marker({ color: 'var(--primary)' }).setLngLat(personCoordinates)]}
            style={{ height: '14rem' }}
        />
    )
}

type NotebookNodeMapAttributes = {}

export const NotebookNodeMap = createPostHogWidgetNode<NotebookNodeMapAttributes>({
    nodeType: NotebookNodeType.Map,
    titlePlaceholder: 'Map',
    Component,
    resizeable: false,
    expandable: false,
    attributes: {},
})
