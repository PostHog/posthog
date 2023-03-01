import { FEATURE_FLAGS } from './../../../lib/constants'
import { featureFlagLogic } from './../../../lib/logic/featureFlagLogic'
import { InsightType } from './../../../types'
import { insightLogic } from './../insightLogic'
import { kea, path, connect, actions, reducers, props, selectors } from 'kea'

import type { samplingFilterLogicType } from './samplingFilterLogicType'
import { InsightLogicProps } from '~/types'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { retentionLogic } from 'scenes/retention/retentionLogic'

export const AVAILABLE_SAMPLING_PERCENTAGES = [0.1, 1, 10, 25]

const INSIGHT_TYPES_WITH_SAMPLING_SUPPORT = new Set([
    InsightType.LIFECYCLE,
    InsightType.FUNNELS,
    InsightType.TRENDS,
    InsightType.RETENTION,
])

interface SamplingFilterLogicProps {
    insightProps: InsightLogicProps
    insightType?: InsightType
}

export const samplingFilterLogic = kea<samplingFilterLogicType>([
    path(['scenes', 'insights', 'EditorFilters', 'samplingFilterLogic']),
    props({} as SamplingFilterLogicProps),
    connect((props: SamplingFilterLogicProps) => ({
        actions: [
            insightLogic(props.insightProps),
            ['setFilters as setInsightFilters'],
            funnelLogic(props.insightProps),
            ['setFilters as setFunnelFilters'],
            retentionLogic(props.insightProps),
            ['setFilters as setRetentionFilters'],
        ],
        values: [insightLogic(props.insightProps), ['filters'], featureFlagLogic, ['featureFlags']],
    })),
    actions(({ actions, props, values }) => ({
        setSamplingPercentage: (samplingPercentage: number) => {
            // clicking on the active button untoggles it and disables sampling
            const samplingFactor = samplingPercentage === values.samplingPercentage ? null : samplingPercentage / 100

            if (props.insightType === InsightType.FUNNELS) {
                actions.setFunnelFilters({
                    ...values.filters,
                    sampling_factor: samplingFactor,
                })
            } else if (props.insightType === InsightType.RETENTION) {
                actions.setRetentionFilters({
                    ...values.filters,
                    sampling_factor: samplingFactor,
                })
            } else {
                actions.setInsightFilters({
                    ...values.filters,
                    sampling_factor: samplingFactor,
                })
            }
            return { samplingPercentage: samplingPercentage === values.samplingPercentage ? null : samplingPercentage }
        },
    })),
    reducers(({ values }) => ({
        samplingPercentage: [
            (values.filters.sampling_factor ? values.filters.sampling_factor * 100 : null) as number | null,
            {
                setSamplingPercentage: (_, { samplingPercentage }) => samplingPercentage,
            },
        ],
    })),
    selectors(({ props }) => ({
        suggestedSamplingPercentage: [
            (s) => [s.samplingPercentage],
            (samplingPercentage): number | null => {
                // 10 is our suggested sampling percentage for those not sampling at all
                if (!samplingPercentage || samplingPercentage > 10) {
                    return 10
                }

                // we can't suggest a percentage for those already sampling at the lowest possible rate
                if (samplingPercentage === AVAILABLE_SAMPLING_PERCENTAGES[0]) {
                    return null
                }

                // for those sampling at a rate less than 10, let's suggest they go even lower
                return AVAILABLE_SAMPLING_PERCENTAGES[AVAILABLE_SAMPLING_PERCENTAGES.indexOf(samplingPercentage) - 1]
            },
        ],
        samplingAvailable: [
            (s) => s.featureFlags,
            (featureFlags: Record<string, boolean | string | undefined>): boolean =>
                featureFlags[FEATURE_FLAGS.SAMPLING] &&
                props.insightType &&
                INSIGHT_TYPES_WITH_SAMPLING_SUPPORT.has(props.insightType),
        ],
    })),
])
