import { kea, path, connect, actions, reducers, props, selectors, listeners } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { featureFlagLogic } from './../../../lib/logic/featureFlagLogic'
import { globalInsightLogic } from 'scenes/insights/globalInsightLogic'
import { insightLogic } from './../insightLogic'
import { insightVizDataLogic } from '../insightVizDataLogic'

import { FEATURE_FLAGS } from './../../../lib/constants'
import { FilterType } from './../../../types'
import { InsightLogicProps } from '~/types'

import type { samplingFilterLogicType } from './samplingFilterLogicType'

export const AVAILABLE_SAMPLING_PERCENTAGES = [0.1, 1, 10, 25]

export interface SamplingFilterLogicProps {
    insightProps: InsightLogicProps
    setFilters?: (filters: Partial<FilterType>) => void
    initialSamplingPercentage?: number | null
}

export const samplingFilterLogic = kea<samplingFilterLogicType>([
    path(['scenes', 'insights', 'EditorFilters', 'samplingFilterLogic']),
    props({} as SamplingFilterLogicProps),
    connect((props: SamplingFilterLogicProps) => ({
        values: [
            insightVizDataLogic(props.insightProps),
            ['querySource'],
            insightLogic(props.insightProps),
            ['filters'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [
            insightLogic(props.insightProps),
            ['setFiltersMerge as updateInsightFilters'],
            globalInsightLogic,
            ['setGlobalInsightFilters'],
        ],
    })),
    actions(() => ({
        setSamplingPercentage: (samplingPercentage: number | null) => ({ samplingPercentage }),
    })),
    reducers(({ props }) => ({
        samplingPercentage: [
            props.initialSamplingPercentage || (null as number | null),
            {
                // clicking on the active button untoggles it and disables sampling
                setSamplingPercentage: (oldSamplingPercentage, { samplingPercentage }) =>
                    samplingPercentage === oldSamplingPercentage ? null : samplingPercentage,
                setGlobalInsightFilters: (_, { globalInsightFilters }) => {
                    return globalInsightFilters.sampling_factor ? globalInsightFilters.sampling_factor * 100 : null
                },
            },
        ],
    })),
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
        samplingAvailable: [
            (s) => [s.featureFlags],
            (featureFlags: Record<string, boolean | string | undefined>): boolean =>
                !!featureFlags[FEATURE_FLAGS.SAMPLING],
        ],
    })),
    listeners(({ props, actions, values }) => ({
        setSamplingPercentage: () => {
            const mergeFilters = {
                sampling_factor: values.samplingPercentage ? values.samplingPercentage / 100 : null,
            }

            if (props.setFilters) {
                // Experiments and data exploration
                props.setFilters(mergeFilters)
            } else {
                actions.updateInsightFilters(mergeFilters)
            }
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
