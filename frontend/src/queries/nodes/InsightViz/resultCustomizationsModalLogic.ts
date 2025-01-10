import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { DataColorToken } from 'lib/colors'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { RESULT_CUSTOMIZATION_DEFAULT } from 'scenes/insights/EditorFilters/ResultCustomizationByPicker'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { getFunnelDatasetKey, getTrendResultCustomizationKey } from 'scenes/insights/utils'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { IndexedTrendResult } from 'scenes/trends/types'

import { ResultCustomizationBy, TrendsFilter } from '~/queries/schema'
import { FlattenedFunnelStepByBreakdown, InsightLogicProps } from '~/types'

import type { resultCustomizationsModalLogicType } from './resultCustomizationsModalLogicType'

export const resultCustomizationsModalLogic = kea<resultCustomizationsModalLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'views', 'InsightsTable', 'resultCustomizationsModalLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic,
            ['isTrends', 'isFunnels', 'insightFilter'],
            trendsDataLogic(props),
            [
                'resultCustomizationBy as resultCustomizationByRaw',
                'resultCustomizations as trendsResultCustomizations',
                'getTrendsColorToken',
            ],
            funnelDataLogic(props),
            ['resultCustomizations as funnelsResultCustomizations', 'getFunnelsColorToken'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [insightVizDataLogic, ['updateInsightFilter']],
    })),

    actions({
        openModal: (dataset: IndexedTrendResult | FlattenedFunnelStepByBreakdown) => ({ dataset }),
        closeModal: true,

        setColorToken: (token: DataColorToken) => ({ token }),

        save: true,
    }),

    reducers({
        dataset: [
            null as IndexedTrendResult | FlattenedFunnelStepByBreakdown | null,
            {
                openModal: (_, { dataset }) => dataset,
                closeModal: () => null,
            },
        ],
        localColorToken: [
            null as DataColorToken | null,
            {
                setColorToken: (_, { token }) => token,
                closeModal: () => null,
            },
        ],
    }),

    selectors({
        hasInsightColors: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.INSIGHT_COLORS],
        ],
        modalVisible: [(s) => [s.dataset], (dataset): boolean => dataset !== null],
        colorToken: [
            (s) => [s.localColorToken, s.colorTokenFromQuery],
            (localColorToken, colorTokenFromQuery): DataColorToken | null => localColorToken || colorTokenFromQuery,
        ],
        colorTokenFromQuery: [
            (s) => [s.isTrends, s.isFunnels, s.getTrendsColorToken, s.getFunnelsColorToken, s.dataset],
            (isTrends, isFunnels, getTrendsColorToken, getFunnelsColorToken, dataset): DataColorToken | null => {
                if (!dataset) {
                    return null
                }

                if (isTrends) {
                    return getTrendsColorToken(dataset as IndexedTrendResult)
                } else if (isFunnels) {
                    return getFunnelsColorToken(dataset as FlattenedFunnelStepByBreakdown)
                }

                return null
            },
        ],
        resultCustomizationBy: [
            (s) => [s.resultCustomizationByRaw],
            (resultCustomizationByRaw) => resultCustomizationByRaw || RESULT_CUSTOMIZATION_DEFAULT,
        ],
        resultCustomizations: [
            (s) => [s.isTrends, s.isFunnels, s.trendsResultCustomizations, s.funnelsResultCustomizations],
            (isTrends, isFunnels, trendsResultCustomizations, funnelsResultCustomizations) => {
                if (isTrends) {
                    return trendsResultCustomizations
                } else if (isFunnels) {
                    return funnelsResultCustomizations
                }

                return null
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        save: () => {
            if (values.localColorToken == null || values.dataset == null) {
                actions.closeModal()
                return
            }

            if (values.isTrends) {
                const resultCustomizationKey = getTrendResultCustomizationKey(
                    values.resultCustomizationBy,
                    values.dataset as IndexedTrendResult
                )
                actions.updateInsightFilter({
                    resultCustomizations: {
                        ...values.trendsResultCustomizations,
                        [resultCustomizationKey]: {
                            assignmentBy: values.resultCustomizationBy,
                            color: values.localColorToken,
                        },
                    },
                } as Partial<TrendsFilter>)
            }

            if (values.isFunnels) {
                const resultCustomizationKey = getFunnelDatasetKey(values.dataset as FlattenedFunnelStepByBreakdown)
                actions.updateInsightFilter({
                    resultCustomizations: {
                        ...values.funnelsResultCustomizations,
                        [resultCustomizationKey]: {
                            assignmentBy: ResultCustomizationBy.Value,
                            color: values.localColorToken,
                        },
                    },
                })
            }

            actions.closeModal()
        },
    })),
])
