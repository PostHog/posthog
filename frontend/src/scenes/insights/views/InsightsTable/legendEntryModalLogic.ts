import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { DataColorToken } from 'lib/colors'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { getTrendLegendColorToken, getTrendLegendEntryKey } from 'scenes/insights/utils'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { GraphDataset, InsightLogicProps } from '~/types'

import type { legendEntryModalLogicType } from './legendEntryModalLogicType'

export const legendEntryModalLogic = kea<legendEntryModalLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'views', 'InsightsTable', 'legendEntryModalLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [trendsDataLogic(props), ['resultCustomizationBy', 'legendEntries'], dataThemeLogic, ['getTheme']],
        actions: [trendsDataLogic(props), ['updateLegendEntry']],
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
            (s) => [s.resultCustomizationBy, s.legendEntries, s.getTheme, s.dataset],
            (resultCustomizationBy, legendEntries, getTheme, dataset): DataColorToken | null => {
                if (!dataset) {
                    return null
                }

                const theme = getTheme('posthog')
                return getTrendLegendColorToken(resultCustomizationBy, legendEntries, theme, dataset)
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        save: () => {
            if (values.localColorToken != null) {
                const legendEntryKey = getTrendLegendEntryKey(values.resultCustomizationBy, values.dataset)
                actions.updateLegendEntry(legendEntryKey, { color: values.localColorToken })
            }

            actions.closeModal()
        },
    })),
])
