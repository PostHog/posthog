import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import {
    breakdownFilterToTaxonomicFilterType,
    filterToTaxonomicFilterType,
    propertyFilterTypeToPropertyDefinitionType,
} from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { InsightLogicProps } from '~/types'

import type { breakdownTagLogicType } from './breakdownTagLogicType'
import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'
import { isURLNormalizeable } from './taxonomicBreakdownFilterUtils'

export interface BreakdownTagLogicProps {
    insightProps: InsightLogicProps
    breakdown: string | number
    breakdownType: string
    isTrends: boolean
}

export const breakdownTagLogic = kea<breakdownTagLogicType>([
    props({} as BreakdownTagLogicProps),
    key(({ insightProps, breakdown }) => `${keyForInsightLogicProps('new')(insightProps)}-${breakdown}`),
    path((key) => ['scenes', 'insights', 'BreakdownFilter', 'breakdownTagLogic', key]),
    connect(() => ({
        values: [
            propertyDefinitionsModel,
            ['getPropertyDefinition'],
            cohortsModel,
            ['cohortsById'],
            taxonomicBreakdownFilterLogic,
            [
                'isMultipleBreakdownsEnabled',
                'histogramBinsUsed as globalHistogramBinsUsed',
                'histogramBinCount as globalBinCount',
                'normalizeBreakdownUrl as globalNormalizeBreakdownUrl',
                'breakdownFilter',
            ],
        ],
        actions: [
            taxonomicBreakdownFilterLogic,
            [
                'removeBreakdown as removeBreakdownFromList',
                'setHistogramBinCount as setHistogramBinCountInList',
                'setNormalizeBreakdownURL as setNormalizeBreakdownURLInList',
                'setHistogramBinsUsed as setHistogramBinsUsedInList',
            ],
        ],
    })),
    actions(() => ({
        removeBreakdown: true,
        setHistogramBinCount: (count: number) => ({
            count,
        }),
        setHistogramBinsUsed: (binsUsed: boolean) => ({
            binsUsed,
        }),
        setNormalizeBreakdownURL: (normalizeURL: boolean) => ({
            normalizeURL,
        }),
    })),
    reducers({
        localHistogramBinCount: [
            undefined as number | undefined,
            {
                setHistogramBinCount: (_, { count }) => count,
            },
        ],
        localNormalizeBreakdownURL: [
            true as boolean,
            {
                setNormalizeBreakdownURL: (_, { normalizeURL }) => normalizeURL,
            },
        ],
    }),
    selectors({
        breakdown: [(_, props) => [props.breakdown], (breakdown) => breakdown],
        breakdownType: [(_, props) => [props.breakdownType], (breakdownType) => breakdownType],
        propertyDefinition: [
            (s, p) => [s.getPropertyDefinition, p.breakdown, p.breakdownType],
            (getPropertyDefinition, breakdown, breakdownType) =>
                getPropertyDefinition(breakdown, propertyFilterTypeToPropertyDefinitionType(breakdownType)),
        ],
        isHistogramable: [
            (s, p) => [p.isTrends, s.propertyDefinition],
            (isTrends, propertyDefinition) => isTrends && !!propertyDefinition?.is_numerical,
        ],
        isNormalizeable: [
            (s) => [s.propertyDefinition],
            (propertyDefinition) => isURLNormalizeable(propertyDefinition?.name || ''),
        ],
        multipleBreakdown: [
            (s) => [s.breakdownFilter, s.breakdown, s.breakdownType],
            ({ breakdowns }, breakdown, breakdownType) =>
                breakdowns?.find(
                    (savedBreakdown) => savedBreakdown.property === breakdown && savedBreakdown.type === breakdownType
                ),
        ],
        histogramBinsUsed: [
            (s) => [s.isMultipleBreakdownsEnabled, s.multipleBreakdown, s.globalHistogramBinsUsed],
            (isMultipleBreakdownsEnabled, multipleBreakdown, globalHistogramBinsUsed) => {
                if (isMultipleBreakdownsEnabled) {
                    return multipleBreakdown?.histogram_bin_count != null
                }

                return globalHistogramBinsUsed
            },
        ],
        histogramBinCount: [
            (s) => [s.isMultipleBreakdownsEnabled, s.localHistogramBinCount, s.globalBinCount, s.multipleBreakdown],
            (isMultipleBreakdownsEnabled, localHistogramBinCount, globalBinCount, multipleBreakdown) => {
                if (isMultipleBreakdownsEnabled) {
                    return localHistogramBinCount ?? multipleBreakdown?.histogram_bin_count ?? 10
                }

                return globalBinCount
            },
        ],
        normalizeBreakdownURL: [
            (s) => [
                s.isMultipleBreakdownsEnabled,
                s.localNormalizeBreakdownURL,
                s.globalNormalizeBreakdownUrl,
                s.multipleBreakdown,
            ],
            (
                isMultipleBreakdownsEnabled,
                localNormalizeBreakdownURL,
                globalNormalizeBreakdownUrl,
                multipleBreakdown
            ) => {
                if (isMultipleBreakdownsEnabled) {
                    return localNormalizeBreakdownURL ?? multipleBreakdown?.normalize_url ?? true
                }

                return globalNormalizeBreakdownUrl
            },
        ],
        taxonomicBreakdownType: [
            (s) => [s.isMultipleBreakdownsEnabled, s.breakdownFilter, s.multipleBreakdown],
            (isMultipleBreakdownsEnabled, breakdownFilter, multipleBreakdown): TaxonomicFilterGroupType | undefined => {
                let breakdownType = isMultipleBreakdownsEnabled
                    ? filterToTaxonomicFilterType(
                          multipleBreakdown?.type,
                          multipleBreakdown?.group_type_index,
                          multipleBreakdown?.property
                      )
                    : breakdownFilterToTaxonomicFilterType(breakdownFilter)

                if (breakdownType === TaxonomicFilterGroupType.Cohorts) {
                    breakdownType = TaxonomicFilterGroupType.CohortsWithAllUsers
                }

                return breakdownType
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        removeBreakdown: () => {
            actions.removeBreakdownFromList(values.breakdown, values.breakdownType)
        },
        setHistogramBinCount: ({ count }) => {
            actions.setHistogramBinCountInList(values.breakdown, values.breakdownType, count)
        },
        setNormalizeBreakdownURL: ({ normalizeURL }) => {
            actions.setNormalizeBreakdownURLInList(values.breakdown, values.breakdownType, normalizeURL)
        },
        setHistogramBinsUsed: ({ binsUsed }) => {
            actions.setHistogramBinsUsedInList(
                values.breakdown,
                values.breakdownType,
                binsUsed,
                values.histogramBinCount
            )
        },
    })),
])
