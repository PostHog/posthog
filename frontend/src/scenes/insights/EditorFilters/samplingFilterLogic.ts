import { kea, path, connect, actions, reducers, props, selectors, listeners } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { globalInsightLogic } from 'scenes/insights/globalInsightLogic'
import { insightVizDataLogic } from '../insightVizDataLogic'

import { InsightLogicProps } from '~/types'

import type { samplingFilterLogicType } from './samplingFilterLogicType'

export const AVAILABLE_SAMPLING_PERCENTAGES = [0.1, 1, 10, 25]

export const samplingFilterLogic = kea<samplingFilterLogicType>([
    path(['scenes', 'insights', 'EditorFilters', 'samplingFilterLogic']),
    props({} as InsightLogicProps),
    connect((props: InsightLogicProps) => ({
        values: [insightVizDataLogic(props), ['querySource']],
        actions: [insightVizDataLogic(props), ['updateQuerySource'], globalInsightLogic, ['setGlobalInsightFilters']],
    })),
    actions(() => ({
        setSamplingPercentage: (samplingPercentage: number | null) => ({ samplingPercentage }),
    })),
    reducers({
        samplingPercentage: [
            null as number | null,
            {
                // clicking on the active button untoggles it and disables sampling
                setSamplingPercentage: (oldSamplingPercentage, { samplingPercentage }) =>
                    samplingPercentage === oldSamplingPercentage ? null : samplingPercentage,
                setGlobalInsightFilters: (_, { globalInsightFilters }) => {
                    return globalInsightFilters.sampling_factor ? globalInsightFilters.sampling_factor * 100 : null
                },
            },
        ],
    }),
    selectors(() => ({
        suggestedSamplingPercentage: [
            (s) => [s.samplingPercentage],
            (samplingPercentage): number | null => {
                // 10 is our suggested sampling percentage for those not sampling at all
                if (!samplingPercentage || samplingPercentage > 10) {
                    return 10
                }

                // we can't suggest a percentage for those already sampling at or below the lowest possible suggestion
                if (samplingPercentage <= AVAILABLE_SAMPLING_PERCENTAGES[0]) {
                    return null
                }

                // for those sampling at a rate less than 10, let's suggest they go even lower
                return AVAILABLE_SAMPLING_PERCENTAGES[AVAILABLE_SAMPLING_PERCENTAGES.indexOf(samplingPercentage) - 1]
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        setSamplingPercentage: () => {
            actions.updateInsightFilters({
                sampling_factor: values.samplingPercentage ? values.samplingPercentage / 100 : null,
            })
        },
    })),
    subscriptions(({ values, actions }) => ({
        querySource: (querySource) => {
            const newSamplingPercentage = querySource?.samplingFactor ? querySource.samplingFactor * 100 : null
            if (newSamplingPercentage !== values.samplingPercentage) {
                actions.setSamplingPercentage(newSamplingPercentage)
            }
        },
    })),
])
