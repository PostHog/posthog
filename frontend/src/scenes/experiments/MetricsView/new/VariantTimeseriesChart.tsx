import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { ProcessedChartData } from '../../experimentTimeseriesLogic'
import { LegacyVariantTimeseriesChart } from './LegacyVariantTimeseriesChart'
import { QuillVariantTimeseriesChart } from './QuillVariantTimeseriesChart'

export interface VariantTimeseriesChartProps {
    chartData: ProcessedChartData
    isRatioMetric?: boolean
}

export function VariantTimeseriesChart(props: VariantTimeseriesChartProps): JSX.Element {
    const quillEnabled = useFeatureFlag('EXPERIMENTS_QUILL_TIMESERIES_CHART')

    if (quillEnabled) {
        return <QuillVariantTimeseriesChart {...props} />
    }

    return <LegacyVariantTimeseriesChart {...props} />
}
