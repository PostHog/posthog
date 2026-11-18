import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { LemonSelect, LemonSelectOption } from 'lib/lemon-ui/LemonSelect'
import { capitalizeFirstLetter, pluralize } from 'lib/utils/strings'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { ExperimentMetric } from '~/queries/schema/schema-general'
import { FunnelConversionWindowTimeUnit } from '~/types'

import { TIME_INTERVAL_BOUNDS } from 'products/product_analytics/frontend/insights/funnels/funnelUtils'

export function ConversionWindowHelp(): JSX.Element {
    return (
        <>
            Controls how long a metric value is considered relevant to an experiment exposure:
            <ul className="list-disc pl-4">
                <li>
                    <strong>Experiment duration</strong> considers any data from when a user is first exposed until the
                    experiment ends.
                </li>
                <li>
                    <strong>Time window</strong> only includes data that occurs within the specified time window after a
                    user's first exposure (also ignoring the experiment end date).
                </li>
            </ul>
        </>
    )
}

export const CONVERSION_WINDOW_MODES = [
    { value: 'experiment_duration', label: 'Experiment duration' },
    { value: 'time_window', label: 'Time window' },
] as const

export function conversionWindowUnitOptions(
    metric: ExperimentMetric
): { label: string; value: FunnelConversionWindowTimeUnit }[] {
    return Object.keys(TIME_INTERVAL_BOUNDS).map((unit) => ({
        label: capitalizeFirstLetter(pluralize(metric.conversion_window ?? 72, unit, `${unit}s`, false)),
        value: unit as FunnelConversionWindowTimeUnit,
    }))
}

export function conversionWindowModeChange(
    metric: ExperimentMetric,
    mode: 'experiment_duration' | 'time_window'
): ExperimentMetric {
    return {
        ...metric,
        conversion_window: mode === 'experiment_duration' ? undefined : 14,
        conversion_window_unit: mode === 'experiment_duration' ? undefined : FunnelConversionWindowTimeUnit.Day,
    }
}

export function ExperimentMetricConversionWindowFilter({
    metric,
    handleSetMetric,
}: {
    metric: ExperimentMetric
    handleSetMetric: (newMetric: ExperimentMetric) => void
}): JSX.Element {
    const options: LemonSelectOption<FunnelConversionWindowTimeUnit>[] = conversionWindowUnitOptions(metric)
    const intervalBounds = TIME_INTERVAL_BOUNDS[metric.conversion_window_unit ?? FunnelConversionWindowTimeUnit.Day]

    return (
        <SceneSection title="Conversion window limit" titleHelper={<ConversionWindowHelp />}>
            <div className="flex flex-col gap-2">
                <LemonRadio
                    className="my-1.5"
                    value={metric.conversion_window_unit === undefined ? 'experiment_duration' : 'time_window'}
                    orientation="horizontal"
                    onChange={(value) => handleSetMetric(conversionWindowModeChange(metric, value))}
                    options={[...CONVERSION_WINDOW_MODES]}
                />
                {metric.conversion_window_unit !== undefined && (
                    <div className="flex items-center gap-2">
                        <LemonInput
                            type="number"
                            className="max-w-20"
                            fullWidth={false}
                            min={intervalBounds[0]}
                            max={intervalBounds[1]}
                            // NaN renders as empty and keeps the input controlled; undefined would not
                            value={metric.conversion_window ?? NaN}
                            onChange={(value) => {
                                handleSetMetric({ ...metric, conversion_window: value || undefined })
                            }}
                        />
                        <LemonSelect
                            dropdownMatchSelectWidth={false}
                            value={metric.conversion_window_unit}
                            onChange={(value) =>
                                handleSetMetric({ ...metric, conversion_window_unit: value || undefined })
                            }
                            options={options}
                        />
                    </div>
                )}
            </div>
        </SceneSection>
    )
}
