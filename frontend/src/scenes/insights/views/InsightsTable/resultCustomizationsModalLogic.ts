import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { DataColorToken } from 'lib/colors'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { getTrendResultCustomizationColorToken, getTrendResultCustomizationKey } from 'scenes/insights/utils'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { GraphDataset, InsightLogicProps } from '~/types'

import type { resultCustomizationsModalLogicType } from './resultCustomizationsModalLogicType'

export const resultCustomizationsModalLogic = kea<resultCustomizationsModalLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'views', 'InsightsTable', 'resultCustomizationsModalLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [
            trendsDataLogic(props),
            ['resultCustomizationBy', 'resultCustomizations'],
            dataThemeLogic,
            ['getTheme'],
        ],
        actions: [trendsDataLogic(props), ['updateResultCustomization']],
    })),

    actions({
        openModal: (dataset: GraphDataset) => ({ dataset }),
        closeModal: true,

        setColorToken: (token: DataColorToken) => ({ token }),

        save: true,
    }),

    reducers({
        dataset: [
            null as GraphDataset | null,
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
            (s) => [s.resultCustomizationBy, s.resultCustomizations, s.getTheme, s.dataset],
            (resultCustomizationBy, resultCustomizations, getTheme, dataset): DataColorToken | null => {
                if (!dataset) {
                    return null
                }

                const theme = getTheme('posthog')
                return getTrendResultCustomizationColorToken(
                    resultCustomizationBy,
                    resultCustomizations,
                    theme,
                    dataset
                )
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        save: () => {
            if (values.localColorToken != null) {
                const resultCustomizationKey = getTrendResultCustomizationKey(
                    values.resultCustomizationBy,
                    values.dataset
                )
                actions.updateResultCustomization(resultCustomizationKey, { color: values.localColorToken })
            }

            actions.closeModal()
        },
    })),
])
