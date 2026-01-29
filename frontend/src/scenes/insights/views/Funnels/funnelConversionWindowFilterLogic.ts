import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { FunnelsFilter } from '~/queries/schema/schema-general'
import { FunnelConversionWindowTimeUnit, InsightLogicProps } from '~/types'

import { funnelDataLogic } from '../../../funnels/funnelDataLogic'
import type { funnelConversionWindowFilterLogicType } from './funnelConversionWindowFilterLogicType'

export const TIME_INTERVAL_BOUNDS: Record<FunnelConversionWindowTimeUnit, [number, number]> = {
    [FunnelConversionWindowTimeUnit.Second]: [1, 3600],
    [FunnelConversionWindowTimeUnit.Minute]: [1, 1440],
    [FunnelConversionWindowTimeUnit.Hour]: [1, 24],
    [FunnelConversionWindowTimeUnit.Day]: [1, 365],
    [FunnelConversionWindowTimeUnit.Week]: [1, 53],
    [FunnelConversionWindowTimeUnit.Month]: [1, 12],
}

const DEFAULT_FUNNEL_WINDOW_INTERVAL = 14
const DEFAULT_FUNNEL_WINDOW_INTERVAL_UNIT = FunnelConversionWindowTimeUnit.Day

export const funnelConversionWindowFilterLogic = kea<funnelConversionWindowFilterLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'views', 'Funnels', 'funnelConversionWindowFilterLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [funnelDataLogic(props), ['insightFilter']],
        actions: [funnelDataLogic(props), ['updateInsightFilter']],
    })),

    actions({
        setFunnelWindowInterval: (funnelWindowInterval: number | null) => ({ funnelWindowInterval }),
        setFunnelWindowIntervalUnit: (funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit) => ({
            funnelWindowIntervalUnit,
        }),
        commitFilter: true,
    }),

    reducers({
        funnelWindowInterval: [
            DEFAULT_FUNNEL_WINDOW_INTERVAL as number | null,
            {
                setFunnelWindowInterval: (_, { funnelWindowInterval }) =>
                    funnelWindowInterval !== null && Number.isNaN(funnelWindowInterval) ? null : funnelWindowInterval,
            },
        ],
        funnelWindowIntervalUnit: [
            DEFAULT_FUNNEL_WINDOW_INTERVAL_UNIT as FunnelConversionWindowTimeUnit,
            {
                setFunnelWindowIntervalUnit: (_, { funnelWindowIntervalUnit }) => funnelWindowIntervalUnit,
            },
        ],
    }),

    selectors({
        bounds: [
            (s) => [s.funnelWindowIntervalUnit],
            (funnelWindowIntervalUnit): [number, number] => TIME_INTERVAL_BOUNDS[funnelWindowIntervalUnit],
        ],
        isOutOfBounds: [
            (s) => [s.funnelWindowInterval, s.bounds],
            (funnelWindowInterval, [min, max]): boolean =>
                funnelWindowInterval !== null && (funnelWindowInterval < min || funnelWindowInterval > max),
        ],
        validationError: [
            (s) => [s.isOutOfBounds, s.bounds],
            (isOutOfBounds, [min, max]): string | undefined =>
                isOutOfBounds ? `Value must be between ${min} and ${max}` : undefined,
        ],
    }),

    listeners(({ values, actions }) => ({
        commitFilter: () => {
            if (values.funnelWindowInterval !== null && !values.isOutOfBounds) {
                actions.updateInsightFilter({
                    funnelWindowInterval: values.funnelWindowInterval,
                    funnelWindowIntervalUnit: values.funnelWindowIntervalUnit,
                })
            }
        },
        setFunnelWindowIntervalUnit: () => {
            actions.commitFilter()
        },
    })),

    subscriptions(({ values, actions }) => ({
        insightFilter: (insightFilter: FunnelsFilter) => {
            const newInterval = insightFilter?.funnelWindowInterval ?? DEFAULT_FUNNEL_WINDOW_INTERVAL
            const newUnit = insightFilter?.funnelWindowIntervalUnit ?? DEFAULT_FUNNEL_WINDOW_INTERVAL_UNIT
            if (newInterval !== values.funnelWindowInterval) {
                actions.setFunnelWindowInterval(newInterval)
            }
            if (newUnit !== values.funnelWindowIntervalUnit) {
                actions.setFunnelWindowIntervalUnit(newUnit)
            }
        },
    })),
])
