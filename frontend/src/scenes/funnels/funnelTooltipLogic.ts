import { actions, kea, key, path, props, reducers } from 'kea'

import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { FunnelStepWithConversionMetrics, InsightLogicProps } from '~/types'

import type { funnelTooltipLogicType } from './funnelTooltipLogicType'

const DEFAULT_FUNNEL_LOGIC_KEY = 'default_funnel_key'

export const funnelTooltipLogic = kea<funnelTooltipLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_FUNNEL_LOGIC_KEY)),
    path((key) => ['scenes', 'funnels', 'funnelTooltipLogic', key]),
    actions({
        showTooltip: (
            origin: [number, number, number],
            stepIndex: number,
            series: FunnelStepWithConversionMetrics
        ) => ({
            origin,
            stepIndex,
            series,
        }),
        hideTooltip: true,
    }),
    reducers({
        isTooltipShown: [
            false,
            {
                showTooltip: () => true,
                hideTooltip: () => false,
            },
        ],
        currentTooltip: [
            null as [number, FunnelStepWithConversionMetrics] | null,
            {
                showTooltip: (_, { stepIndex, series }) => [stepIndex, series],
            },
        ],
        tooltipOrigin: [
            null as [number, number, number] | null, // x, y, width
            {
                showTooltip: (_, { origin }) => origin,
            },
        ],
    }),
])
