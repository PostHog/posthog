import { useValues } from 'kea'
import maplibregl, { Popup } from 'maplibre-gl'
import { Protocol } from 'pmtiles'
import layers from 'protomaps-themes-base'
import { useEffect, useRef } from 'react'
import useResizeObserver from 'use-resize-observer'

import { compactNumber } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { ChartParams, TrendResult } from '~/types'

import { insightLogic } from '../../insightLogic'
import { adminGeoDataLogic } from './adminGeoDataLogic'
import { InteractiveWorldMapMode, interactiveWorldMapLogic } from './interactiveWorldMapLogic'

const protocol = new Protocol()
maplibregl.addProtocol('pmtiles', protocol.tile)

const isDev = process.env.NODE_ENV === 'development'
const BASE_URL = isDev ? 'http://localhost:8234/pmtiles' : 'https://posthog-prod-maps.s3.us-east-1.amazonaws.com'
const PMTILES_URL = `pmtiles://${BASE_URL}/20230913.pmtiles`
const GLYPH_URL = `${BASE_URL}/fonts/pbf/{fontstack}/{range}.pbf`

const createPopupContent = (text: string, subtext?: string): HTMLElement => {
    const container = document.createElement('div')
    const strong = document.createElement('strong')
    strong.textContent = text
    container.appendChild(strong)
    if (subtext) {
        container.appendChild(document.createElement('br'))
        container.appendChild(document.createTextNode(subtext))
    }
    return container
}

const setupPointsOverlay = (
    map: maplibregl.Map,
    geoJSON: GeoJSON.FeatureCollection,
    backgroundColor: string,
    aggregationLabel: string
): Popup => {
    map.addSource('points', {
        type: 'geojson',
        data: geoJSON,
        cluster: true,
        clusterMaxZoom: 14,
        clusterRadius: 50,
    })

    map.addLayer({
        id: 'points-layer',
        type: 'circle',
        source: 'points',
        paint: {
            'circle-color': backgroundColor,
            'circle-radius': [
                'case',
                ['has', 'point_count'],
                // This syntax is slight weird. Effectively, this is setting the circle size based on
                // the number of points in a cluster:
                // Default: 20px
                // >= 10 points: 25px
                // >= 50 points: 30px
                // >= 200 points: 40px
                ['step', ['get', 'point_count'], 20, 10, 25, 50, 30, 200, 40],
                // If it's a single point, the circle size is 10px
                10,
            ],
            'circle-opacity': 0.9,
            'circle-stroke-width': 1,
            'circle-stroke-color': '#ffffff',
        },
    })

    map.on('click', 'points-layer', (event) => {
        const feature = event.features?.at(0)
        if (!feature || feature.geometry.type !== 'Point') {
            return
        }

        const coords = feature.geometry.coordinates as [number, number]

        if (feature.properties?.cluster_id) {
            const source = map.getSource('points') as maplibregl.GeoJSONSource

            source.getClusterExpansionZoom(feature.properties.cluster_id, (err, expansionZoom) => {
                if (!err && expansionZoom != null) {
                    map.easeTo({ center: coords, zoom: expansionZoom })
                }
            })
        } else {
            map.flyTo({ center: coords, zoom: 10 })
        }
    })

    map.on('mouseenter', 'points-layer', () => {
        map.getCanvas().style.cursor = 'pointer'
    })
    map.on('mouseleave', 'points-layer', () => {
        map.getCanvas().style.cursor = ''
    })

    const popup = new Popup({ closeButton: false, closeOnClick: false })

    map.on('mousemove', 'points-layer', (event) => {
        const props = event.features?.at(0)?.properties
        if (!props) {
            return
        }

        const content = props.cluster_id
            ? createPopupContent(`${props.point_count} locations`)
            : createPopupContent(props.label || 'Location', `${compactNumber(props.value || 0)} ${aggregationLabel}`)

        popup.setLngLat(event.lngLat).setDOMContent(content).addTo(map)
    })

    map.on('mouseleave', 'points-layer', () => popup.remove())

    return popup
}

const setupSubdivisionsOverlay = (
    map: maplibregl.Map,
    geoJSON: GeoJSON.FeatureCollection,
    seriesByIsoCode: Record<string, TrendResult>,
    aggregationLabel: string,
    onDataPointClick?: (data: { breakdown: string[] }, series: TrendResult) => void
): Popup => {
    map.addSource('subdivisions', {
        type: 'geojson',
        data: geoJSON,
    })

    const hasDataFilter: maplibregl.FilterSpecification = ['==', ['get', '_hasData'], true]

    map.addLayer({
        id: 'subdivisions-fill',
        type: 'fill',
        source: 'subdivisions',
        paint: { 'fill-color': ['get', '_color'], 'fill-opacity': 1 },
        filter: hasDataFilter,
    })

    map.addLayer({
        id: 'subdivisions-outline',
        type: 'line',
        source: 'subdivisions',
        paint: {
            'line-color': 'rgba(0, 0, 0, 0.2)',
            'line-width': 0.5,
        },
        filter: hasDataFilter,
    })

    map.on('mouseenter', 'subdivisions-fill', () => {
        map.getCanvas().style.cursor = 'pointer'
    })
    map.on('mouseleave', 'subdivisions-fill', () => {
        map.getCanvas().style.cursor = ''
    })

    const popup = new Popup({ closeButton: false, closeOnClick: false })

    map.on('mousemove', 'subdivisions-fill', (event) => {
        const props = event.features?.at(0)?.properties
        if (!props) {
            return
        }

        const name = props.iso_a2 ? `${props.name}, ${props.iso_a2}` : props.name || 'Unknown'
        const content = createPopupContent(name, `${(props._value || 0).toLocaleString()} ${aggregationLabel}`)
        popup.setLngLat(event.lngLat).setDOMContent(content).addTo(map)
    })

    map.on('mouseleave', 'subdivisions-fill', () => popup.remove())

    if (onDataPointClick) {
        map.on('click', 'subdivisions-fill', (event) => {
            const isoCode = event.features?.at(0)?.properties?.iso_3166_2
            const series = isoCode ? seriesByIsoCode[isoCode] : undefined

            if (series) {
                onDataPointClick({ breakdown: series.breakdown_value as string[] }, series)
                popup.remove()
            }
        })
    }

    return popup
}

export const InteractiveWorldMap = ({ context }: ChartParams): JSX.Element => {
    const { isCloudOrDev } = useValues(preflightLogic)
    const { insightProps } = useValues(insightLogic)
    const { adminGeoDataLoading } = useValues(adminGeoDataLogic)

    const { visualizationMode, isDarkModeOn, backgroundColor, groupTypeLabel, center, geoJSON, seriesByIsoCode } =
        useValues(interactiveWorldMapLogic(insightProps))

    const mapContainer = useRef<HTMLDivElement>(null)
    const map = useRef<maplibregl.Map | null>(null)
    const mapReady = useRef<boolean>(false)
    const popupRef = useRef<Popup | null>(null)

    useEffect(() => {
        if (!mapContainer.current) {
            return
        }

        mapReady.current = false
        map.current = new maplibregl.Map({
            container: mapContainer.current,
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
            zoom: 1,
            maxZoom: 16,
        })

        map.current.on('load', () => {
            if (!map.current) {
                return
            }

            if (visualizationMode === InteractiveWorldMapMode.Points) {
                popupRef.current = setupPointsOverlay(map.current, geoJSON, backgroundColor, groupTypeLabel)
            } else {
                popupRef.current = setupSubdivisionsOverlay(
                    map.current,
                    geoJSON,
                    seriesByIsoCode,
                    groupTypeLabel,
                    context?.onDataPointClick
                )
            }
            mapReady.current = true
        })

        return () => {
            mapReady.current = false
            popupRef.current?.remove()
            popupRef.current = null
            map.current?.remove()
        }
    }, [
        visualizationMode,
        isDarkModeOn,
        geoJSON,
        context?.onDataPointClick,
        backgroundColor,
        groupTypeLabel,
        center,
        seriesByIsoCode,
    ])

    useResizeObserver({
        ref: mapContainer,
        onResize: () => map.current?.resize(),
    })

    if (!isCloudOrDev) {
        return (
            <div className="w-full h-full flex flex-col items-center justify-center text-secondary p-3">
                <h1>Map unavailable</h1>
                <p>The map is currently only available in cloud deployments.</p>
            </div>
        )
    }

    if (adminGeoDataLoading) {
        return (
            <div className="w-full h-full min-h-125 flex items-center justify-center text-secondary">
                Loading map data...
            </div>
        )
    }

    return <div ref={mapContainer} className="w-full h-full min-h-125" />
}
