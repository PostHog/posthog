import { FeatureCollection } from 'geojson'
import { connect, kea, key, path, props, selectors } from 'kea'

import { isPointsMapBreakdown } from 'scenes/web-analytics/common'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { groupsModel } from '~/models/groupsModel'
import { InsightLogicProps } from '~/types'

import { insightVizDataLogic } from '../../insightVizDataLogic'
import { keyForInsightLogicProps } from '../../sharedUtils'
import type { interactiveWorldMapLogicType } from './interactiveWorldMapLogicType'
import { worldMapPointsLogic } from './worldMapPointsLogic'
import { worldMapSubdivisionsLogic } from './worldMapSubdivisionsLogic'

export enum InteractiveWorldMapMode {
    Points = 'points',
    Subdivisions = 'subdivisions',
}

export const interactiveWorldMapLogic = kea<interactiveWorldMapLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'WorldMap', 'interactiveWorldMapLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            ['breakdownFilter', 'series'],
            worldMapPointsLogic(props),
            ['points', 'geoJSON as pointsGeoJSON', 'center as pointsCenter', 'hasData as pointsHasData', 'theme'],
            worldMapSubdivisionsLogic(props),
            [
                'subdivisionsByCode',
                'seriesByIsoCode',
                'geoJSON as subdivisionsGeoJSON',
                'center as subdivisionsCenter',
                'hasData as subdivisionsHasData',
                'maxValue as subdivisionsMaxValue',
            ],
            themeLogic,
            ['isDarkModeOn'],
            groupsModel,
            ['aggregationLabel'],
        ],
    })),
    selectors({
        visualizationMode: [
            (s) => [s.breakdownFilter],
            (breakdownFilter): InteractiveWorldMapMode =>
                isPointsMapBreakdown(breakdownFilter?.breakdowns)
                    ? InteractiveWorldMapMode.Points
                    : InteractiveWorldMapMode.Subdivisions,
        ],
        backgroundColor: [(s) => [s.theme], (theme): string => theme?.['preset-1'] || '#000000'],
        groupTypeLabel: [
            (s) => [s.aggregationLabel, s.series],
            (aggregationLabel, series): string => aggregationLabel(series?.[0]?.math_group_type_index).singular,
        ],
        center: [
            (s) => [s.visualizationMode, s.pointsCenter, s.subdivisionsCenter],
            (visualizationMode, pointsCenter, subdivisionsCenter): [number, number] =>
                visualizationMode === InteractiveWorldMapMode.Points ? pointsCenter : subdivisionsCenter,
        ],
        hasData: [
            (s) => [s.visualizationMode, s.pointsHasData, s.subdivisionsHasData],
            (visualizationMode, pointsHasData, subdivisionsHasData): boolean =>
                visualizationMode === InteractiveWorldMapMode.Points ? pointsHasData : subdivisionsHasData,
        ],
        geoJSON: [
            (s) => [s.visualizationMode, s.pointsGeoJSON, s.subdivisionsGeoJSON],
            (
                visualizationMode: InteractiveWorldMapMode,
                pointsGeoJSON: FeatureCollection,
                subdivisionsGeoJSON: FeatureCollection
            ): FeatureCollection =>
                visualizationMode === InteractiveWorldMapMode.Points ? pointsGeoJSON : subdivisionsGeoJSON,
        ],
    }),
])
