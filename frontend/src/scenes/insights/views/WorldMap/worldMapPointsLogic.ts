import { connect, kea, key, path, props, selectors } from 'kea'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { InsightLogicProps, TrendResult } from '~/types'

import { keyForInsightLogicProps } from '../../sharedUtils'
import type { worldMapPointsLogicType } from './worldMapPointsLogicType'

export interface WorldMapPointData {
    lat: number
    lng: number
    value: number
    label: string
}

const isValidCoordinate = (lat: number, lng: number): boolean =>
    !isNaN(lng) && !isNaN(lat) && Math.abs(lng) <= 180 && Math.abs(lat) <= 90

export const worldMapPointsLogic = kea<worldMapPointsLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'WorldMap', 'worldMapPointsLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [insightVizDataLogic(props), ['insightData', 'theme']],
    })),
    selectors({
        points: [
            (s) => [s.insightData],
            (insightData: Record<string, any> | null): WorldMapPointData[] => {
                const results = insightData?.result
                if (!Array.isArray(results)) {
                    return []
                }

                return (results as TrendResult[])
                    .map((series) => {
                        const breakdown = series.breakdown_value
                        if (!Array.isArray(breakdown)) {
                            return null
                        }

                        const [latStr, lngStr] = breakdown
                        const lat = parseFloat(String(latStr))
                        const lng = parseFloat(String(lngStr))

                        if (isNaN(lat) || isNaN(lng)) {
                            return null
                        }

                        return {
                            lat,
                            lng,
                            value: series.aggregated_value ?? 0,
                            label: series.label,
                        }
                    })
                    .filter((p): p is WorldMapPointData => p !== null)
            },
        ],
        center: [
            (s) => [s.points],
            (points: WorldMapPointData[]): [number, number] => {
                if (points.length === 0) {
                    return [0, 20]
                }
                const lngs = points.map((p) => p.lng)
                const lats = points.map((p) => p.lat)
                const minLng = Math.min(...lngs)
                const maxLng = Math.max(...lngs)
                const minLat = Math.min(...lats)
                const maxLat = Math.max(...lats)
                return [(minLng + maxLng) / 2, (minLat + maxLat) / 2]
            },
        ],
        hasData: [(s) => [s.points], (points: WorldMapPointData[]): boolean => points.length > 0],
        geoJSON: [
            (s) => [s.points],
            (points: WorldMapPointData[]): GeoJSON.FeatureCollection => ({
                type: 'FeatureCollection',
                features: points
                    .filter((p) => isValidCoordinate(p.lat, p.lng))
                    .map((p) => ({
                        type: 'Feature' as const,
                        geometry: { type: 'Point' as const, coordinates: [p.lng, p.lat] },
                        properties: { value: p.value, label: `${p.lat},${p.lng}` },
                    })),
            }),
        ],
    }),
])
