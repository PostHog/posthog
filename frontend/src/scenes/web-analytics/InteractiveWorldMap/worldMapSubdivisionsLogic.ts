import { Feature, FeatureCollection } from 'geojson'
import { connect, kea, key, path, props, selectors } from 'kea'

import { hexToRGB } from 'lib/utils'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { InsightLogicProps, TrendResult } from '~/types'

import { adminGeoDataLogic } from './adminGeoDataLogic'
import type { worldMapSubdivisionsLogicType } from './worldMapSubdivisionsLogicType'

const MINIMUM_SUBDIVISION_OPACITY = 0.2
const MAXIMUM_SUBDIVISION_OPACITY = 0.8
const DEFAULT_CENTER: [number, number] = [0, 20]

export interface WorldMapSubdivisionData {
    isoCode: string
    value: number
    label: string
}

export interface ParsedSubdivision {
    isoCode: string
    series: TrendResult
}

const parseSubdivisionFromSeries = (series: TrendResult): ParsedSubdivision | null => {
    const breakdown = series.breakdown_value
    if (!Array.isArray(breakdown) || breakdown.length < 2) {
        return null
    }

    const [countryCode, subdivisionCode] = breakdown
    if (!countryCode || !subdivisionCode) {
        return null
    }

    return {
        isoCode: `${countryCode}-${subdivisionCode}`,
        series,
    }
}

export const worldMapSubdivisionsLogic = kea<worldMapSubdivisionsLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'web-analytics', 'InteractiveWorldMap', 'worldMapSubdivisionsLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            ['insightData', 'theme'],
            adminGeoDataLogic,
            ['adminGeoData', 'adminGeoDataLoading'],
        ],
    })),
    selectors({
        parsedSubdivisions: [
            (s) => [s.insightData],
            (insightData: Record<string, any> | null): ParsedSubdivision[] => {
                const results = insightData?.result
                if (!Array.isArray(results)) {
                    return []
                }

                return (results as TrendResult[])
                    .map(parseSubdivisionFromSeries)
                    .filter((s): s is ParsedSubdivision => s !== null)
            },
        ],
        subdivisionsByCode: [
            (s) => [s.parsedSubdivisions],
            (parsedSubdivisions: ParsedSubdivision[]): Record<string, WorldMapSubdivisionData> => {
                const map: Record<string, WorldMapSubdivisionData> = {}
                for (const { isoCode, series } of parsedSubdivisions) {
                    map[isoCode] = {
                        isoCode,
                        value: series.aggregated_value ?? 0,
                        label: series.label,
                    }
                }
                return map
            },
        ],
        seriesByIsoCode: [
            (s) => [s.parsedSubdivisions],
            (parsedSubdivisions: ParsedSubdivision[]): Record<string, TrendResult> => {
                const map: Record<string, TrendResult> = {}
                for (const { isoCode, series } of parsedSubdivisions) {
                    map[isoCode] = series
                }
                return map
            },
        ],
        maxValue: [
            (s) => [s.subdivisionsByCode],
            (subdivisionsByCode: Record<string, WorldMapSubdivisionData>): number => {
                const values = Object.values(subdivisionsByCode).map((sub) => sub.value)
                if (values.length === 0) {
                    return 0
                }
                return Math.max(...values)
            },
        ],
        backgroundColor: [(s) => [s.theme], (theme): string => theme?.['preset-1'] || '#000000'],
        center: [() => [], (): [number, number] => DEFAULT_CENTER],
        hasData: [
            (s) => [s.subdivisionsByCode],
            (subdivisionsByCode: Record<string, WorldMapSubdivisionData>): boolean =>
                Object.keys(subdivisionsByCode).length > 0,
        ],
        geoJSON: [
            (s) => [s.adminGeoData, s.subdivisionsByCode, s.maxValue, s.backgroundColor],
            (
                adminGeoData: FeatureCollection | null,
                subdivisionsByCode: Record<string, WorldMapSubdivisionData>,
                maxValue: number,
                backgroundColor: string
            ): FeatureCollection | null => {
                if (!adminGeoData) {
                    return null
                }

                const { r, g, b } = hexToRGB(backgroundColor)

                const getColor = (value: number | undefined): string => {
                    if (value === undefined || value <= 0 || maxValue <= 0) {
                        return 'transparent'
                    }
                    const logRatio = Math.log(value + 1) / Math.log(maxValue + 1)
                    const opacityRange = MAXIMUM_SUBDIVISION_OPACITY - MINIMUM_SUBDIVISION_OPACITY
                    const opacity = logRatio * opacityRange + MINIMUM_SUBDIVISION_OPACITY
                    return `rgba(${r}, ${g}, ${b}, ${opacity.toFixed(3)})`
                }

                return {
                    type: 'FeatureCollection',
                    features: adminGeoData.features.map((feature: Feature) => {
                        const isoCode: string | undefined = feature.properties?.iso_3166_2
                        const data = isoCode ? subdivisionsByCode[isoCode] : undefined

                        return {
                            ...feature,
                            properties: {
                                ...feature.properties,
                                _value: data?.value ?? 0,
                                _color: getColor(data?.value),
                                _hasData: !!data,
                            },
                        }
                    }),
                }
            },
        ],
    }),
])
