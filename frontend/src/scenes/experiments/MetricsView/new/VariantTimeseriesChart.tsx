import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { ProcessedChartData } from '../../experimentTimeseriesLogic'
import { LegacyVariantTimeseriesChart } from './LegacyVariantTimeseriesChart'
import { QuillVariantTimeseriesChart } from './QuillVariantTimeseriesChart'

export interface VariantTimeseriesChartProps {
    chartData: ProcessedChartData
    isRatioMetric?: boolean
}

export function VariantTimeseriesChart(props: VariantTimeseriesChartProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_QUILL_TIMESERIES_CHART]) {
        return <QuillVariantTimeseriesChart {...props} />
    }

    return <LegacyVariantTimeseriesChart {...props} />
}
