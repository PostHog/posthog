import { MetricDirectionColorPickers } from 'lib/components/Metric/MetricDirectionColorPickers'
import {
    METRIC_COLOR_BY_DIRECTION_DEFAULT,
    METRIC_DEFAULT_DECREASE_COLOR,
    METRIC_DEFAULT_INCREASE_COLOR,
    METRIC_SHOW_CHANGE_DEFAULT,
    type MetricSummary,
} from 'lib/components/Metric/metricSummary'

import type { MetricChartSettings } from '~/queries/schema/schema-general'

import { ChartOptionSelect } from './ChartOptionSelect'
import { ChartOptionSwitch } from './ChartOptionSwitch'

const SUMMARY_OPTIONS: { value: MetricSummary; label: string }[] = [
    { value: 'total', label: 'Total' },
    { value: 'average', label: 'Average' },
    { value: 'latest', label: 'Latest' },
]

export interface MetricOptionsProps {
    settings: MetricChartSettings
    /** Each screen has its own default headline. */
    defaultSummary: MetricSummary
    onChange: (changes: Partial<MetricChartSettings>) => void
    summaryDataAttr?: string
}

export function MetricOptions({
    settings,
    defaultSummary,
    onChange,
    summaryDataAttr,
}: MetricOptionsProps): JSX.Element {
    const showChange = settings.showChange ?? METRIC_SHOW_CHANGE_DEFAULT
    const colorByDirection = settings.colorByDirection ?? METRIC_COLOR_BY_DIRECTION_DEFAULT

    return (
        <div className="flex flex-col gap-2">
            <ChartOptionSelect
                label="Headline value"
                value={settings.summary ?? defaultSummary}
                options={SUMMARY_OPTIONS}
                onChange={(summary) => onChange({ summary })}
                data-attr={summaryDataAttr}
            />
            <ChartOptionSwitch
                label="Show change"
                checked={showChange}
                onChange={(next) => onChange({ showChange: next })}
            />
            {showChange && (
                <MetricDirectionColorPickers
                    className="gap-2 pl-4"
                    increaseColor={settings.changeIncreaseColor ?? METRIC_DEFAULT_INCREASE_COLOR}
                    decreaseColor={settings.changeDecreaseColor ?? METRIC_DEFAULT_DECREASE_COLOR}
                    onIncrease={(color) => onChange({ changeIncreaseColor: color })}
                    onDecrease={(color) => onChange({ changeDecreaseColor: color })}
                />
            )}
            <ChartOptionSwitch
                label="Color by trend"
                checked={colorByDirection}
                onChange={(next) => onChange({ colorByDirection: next })}
            />
            {colorByDirection && (
                <MetricDirectionColorPickers
                    className="gap-2 pl-4"
                    increaseColor={settings.lineIncreaseColor ?? METRIC_DEFAULT_INCREASE_COLOR}
                    decreaseColor={settings.lineDecreaseColor ?? METRIC_DEFAULT_DECREASE_COLOR}
                    onIncrease={(color) => onChange({ lineIncreaseColor: color })}
                    onDecrease={(color) => onChange({ lineDecreaseColor: color })}
                />
            )}
        </div>
    )
}
