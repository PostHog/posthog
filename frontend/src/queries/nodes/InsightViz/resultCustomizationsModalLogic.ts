import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { DataColorToken } from 'lib/colors'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { getFunnelDatasetKey, getTrendResultCustomization, getTrendResultCustomizationKey } from 'scenes/insights/utils'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { IndexedTrendResult } from 'scenes/trends/types'

import { ResultCustomizationBy, TrendsFilter } from '~/queries/schema/schema-general'
import { FlattenedFunnelStepByBreakdown, InsightLogicProps } from '~/types'

import type { resultCustomizationsModalLogicType } from './resultCustomizationsModalLogicType'

export const resultCustomizationsModalLogic = kea<resultCustomizationsModalLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'views', 'InsightsTable', 'resultCustomizationsModalLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic,
            ['isTrends', 'isStickiness', 'isFunnels', 'insightFilter'],
            trendsDataLogic(props),
            ['resultCustomizationBy', 'resultCustomizations as trendsResultCustomizations', 'getTrendsColorToken'],
            funnelDataLogic(props),
            ['resultCustomizations as funnelsResultCustomizations', 'getFunnelsColorToken'],
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
        modalVisible: [(s) => [s.dataset], (dataset): boolean => dataset !== null],
        colorToken: [
            (s) => [s.localColorToken, s.colorTokenFromQuery],
            (localColorToken, colorTokenFromQuery): DataColorToken | null => localColorToken || colorTokenFromQuery,
        ],
        colorTokenFromQuery: [
            (s) => [s.isTrends, s.isStickiness, s.isFunnels, s.getTrendsColorToken, s.getFunnelsColorToken, s.dataset],
            (
                isTrends,
                isStickiness,
                isFunnels,
                getTrendsColorToken,
                getFunnelsColorToken,
                dataset
            ): DataColorToken | null => {
                if (!dataset) {
                    return null
                }

                if (isTrends || isStickiness) {
                    return getTrendsColorToken(dataset as IndexedTrendResult)[1]
                } else if (isFunnels) {
                    return getFunnelsColorToken(dataset as FlattenedFunnelStepByBreakdown)[1]
                }

                return null
            },
        ],
        resultCustomizations: [
            (s) => [
                s.isTrends,
                s.isStickiness,
                s.isFunnels,
                s.trendsResultCustomizations,
                s.funnelsResultCustomizations,
            ],
            (isTrends, isStickiness, isFunnels, trendsResultCustomizations, funnelsResultCustomizations) => {
                if (isTrends || isStickiness) {
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

            if (values.isTrends || values.isStickiness) {
                const resultCustomizationKey = getTrendResultCustomizationKey(
                    values.resultCustomizationBy,
                    values.dataset as IndexedTrendResult
                )
                const resultCustomization = getTrendResultCustomization(
                    values.resultCustomizationBy,
                    values.dataset as IndexedTrendResult,
                    values.resultCustomizations
                )
                actions.updateInsightFilter({
                    resultCustomizations: {
                        ...values.trendsResultCustomizations,
                        [resultCustomizationKey]: {
                            ...resultCustomization,
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
