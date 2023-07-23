import { kea, props, key, path, selectors, connect } from 'kea'
import { ChartDisplayType, InsightLogicProps } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import {
    FEATURE_FLAGS,
    NON_TIME_SERIES_DISPLAY_TYPES,
    NON_VALUES_ON_SERIES_DISPLAY_TYPES,
    PERCENT_STACK_VIEW_DISPLAY_TYPE,
} from 'lib/constants'

import type { insightDisplayConfigLogicType } from './insightDisplayConfigLogicType'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export const insightDisplayConfigLogic = kea<insightDisplayConfigLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightDataLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            insightVizDataLogic(props),
            [
                'isTrends',
                'isFunnels',
                'isRetention',
                'isPaths',
                'isStickiness',
                'isLifecycle',
                'supportsDisplay',
                'display',
                'breakdown',
                'trendsFilter',
            ],
            funnelDataLogic(props),
            ['isEmptyFunnel', 'isStepsFunnel', 'isTimeToConvertFunnel', 'isTrendsFunnel'],
        ],
    })),

    selectors({
        showDateRange: [(s) => [s.isRetention], (isRetention) => !isRetention],
        disableDateRange: [
            (s) => [s.isFunnels, s.isEmptyFunnel],
            (isFunnels, isEmptyFunnel) => isFunnels && !!isEmptyFunnel,
        ],
        showCompare: [
            (s) => [s.isTrends, s.isStickiness, s.display],
            (isTrends, isStickiness, display) =>
                (isTrends && display !== ChartDisplayType.ActionsAreaGraph) || isStickiness,
        ],
        showValueOnSeries: [
            (s) => [s.isTrends, s.isStickiness, s.isLifecycle, s.display],
            (isTrends, isStickiness, isLifecycle, display) => {
                if (isTrends || isStickiness) {
                    return !NON_VALUES_ON_SERIES_DISPLAY_TYPES.includes(display || ChartDisplayType.ActionsLineGraph)
                } else if (isLifecycle) {
                    return true
                } else {
                    return false
                }
            },
        ],
        showPercentStackView: [
            (s) => [s.isTrends, s.isStickiness, s.isLifecycle, s.display],
            (isTrends, isStickiness, isLifecycle, display) =>
                (isTrends || isStickiness) && display ? PERCENT_STACK_VIEW_DISPLAY_TYPE.includes(display) : isLifecycle,
        ],
        showUnit: [(s) => [s.supportsDisplay, s.isTrends], (supportsDisplay, isTrends) => supportsDisplay && isTrends],
        showChart: [(s) => [s.supportsDisplay], (supportsDisplay) => supportsDisplay],
        showInterval: [
            (s) => [s.isTrends, s.isStickiness, s.isLifecycle, s.isTrendsFunnel, s.display],
            (isTrends, isStickiness, isLifecycle, isTrendsFunnel, display) =>
                isTrendsFunnel ||
                isLifecycle ||
                ((isTrends || isStickiness) && !(display && NON_TIME_SERIES_DISPLAY_TYPES.includes(display))),
        ],
        showSmoothing: [
            (s) => [s.isTrends, s.breakdown, s.display, s.trendsFilter, s.featureFlags],
            (isTrends, breakdown, display, trendsFilter, featureFlags) =>
                isTrends &&
                !breakdown?.breakdown_type &&
                !trendsFilter?.compare &&
                (!display || display === ChartDisplayType.ActionsLineGraph) &&
                featureFlags[FEATURE_FLAGS.SMOOTHING_INTERVAL],
        ],
        showRetention: [(s) => [s.isRetention], (isRetention) => !!isRetention],
        showPaths: [(s) => [s.isPaths], (isPaths) => !!isPaths],
        showFunnelDisplayLayout: [(s) => [s.isStepsFunnel], (isStepsFunnel) => !!isStepsFunnel],
        showFunnelBins: [(s) => [s.isTimeToConvertFunnel], (isTimeToConvertFunnel) => !!isTimeToConvertFunnel],
    }),
])
