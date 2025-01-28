import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { HogQLQueryModifiers } from '~/queries/schema'
import { InsightLogicProps } from '~/types'

import { insightVizDataLogic } from '../insightVizDataLogic'
import type { poeFilterLogicType } from './poeFilterLogicType'

export const AVAILABLE_SAMPLING_PERCENTAGES = [0.1, 1, 10, 25]

export const poeFilterLogic = kea<poeFilterLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'EditorFilters', 'poeFilterLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [insightVizDataLogic(props), ['querySource']],
        actions: [insightVizDataLogic(props), ['updateQuerySource']],
    })),
    actions(() => ({
        setSamplingPercentage: (samplingPercentage: number | null) => ({ samplingPercentage }),
        setPoeMode: (poeMode: HogQLQueryModifiers['personsOnEventsMode'] | null) => ({ poeMode }),
    })),
    reducers({
        samplingPercentage: [
            null as number | null,
            {
                setSamplingPercentage: (_, { samplingPercentage }) => samplingPercentage,
            },
        ],
        poeMode: [
            null as HogQLQueryModifiers['personsOnEventsMode'] | null,
            {
                setPoeMode: (_, { poeMode }) => poeMode,
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
            actions.updateQuerySource({
                samplingFactor: values.samplingPercentage ? values.samplingPercentage / 100 : null,
            })
        },
        setPoeMode: () => {
            actions.updateQuerySource({
                modifiers: {
                    personsOnEventsMode: values.poeMode,
                },
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
