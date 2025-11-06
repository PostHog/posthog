import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { LemonSelect, LemonSelectOption } from 'lib/lemon-ui/LemonSelect'
import { capitalizeFirstLetter, pluralize } from 'lib/utils'
import { TIME_INTERVAL_BOUNDS } from 'scenes/insights/views/Funnels/FunnelConversionWindowFilter'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { ExperimentMetric } from '~/queries/schema/schema-general'
import { FunnelConversionWindowTimeUnit } from '~/types'

export function ExperimentMetricConversionWindowFilter({
    metric,
    handleSetMetric,
}: {
    metric: ExperimentMetric
    handleSetMetric: (newMetric: ExperimentMetric) => void
}): JSX.Element {
    const options: LemonSelectOption<FunnelConversionWindowTimeUnit>[] = Object.keys(TIME_INTERVAL_BOUNDS).map(
        (unit) => ({
            label: capitalizeFirstLetter(pluralize(metric.conversion_window ?? 72, unit, `${unit}s`, false)),
            value: unit as FunnelConversionWindowTimeUnit,
        })
    )
    const intervalBounds = TIME_INTERVAL_BOUNDS[metric.conversion_window_unit ?? FunnelConversionWindowTimeUnit.Day]

    return (
        <SceneSection
            title="Conversion window limit"
            titleHelper={
                <>
                    Controls how long a metric value is considered relevant to an experiment exposure:
                    <ul className="list-disc pl-4">
                        <li>
                            <strong>Experiment duration</strong> considers any data from when a user is first exposed
                            until the experiment ends.
                        </li>
                        <li>
                            <strong>Time window</strong> only includes data that occurs within the specified time window
                            after a user's first exposure (also ignoring the experiment end date).
                        </li>
                    </ul>
                </>
            }
        >
            <div className="flex flex-col gap-2">
                <LemonRadio
                    className="my-1.5"
                    value={metric.conversion_window_unit === undefined ? 'experiment_duration' : 'time_window'}
                    orientation="horizontal"
                    onChange={(value) =>
                        handleSetMetric({
                            ...metric,
                            conversion_window: value === 'experiment_duration' ? undefined : 14,
                            conversion_window_unit:
                                value === 'experiment_duration' ? undefined : FunnelConversionWindowTimeUnit.Day,
                        })
                    }
                    options={[
                        {
                            value: 'experiment_duration',
                            label: 'Experiment duration',
                        },
                        {
                            value: 'time_window',
                            label: 'Time window',
                        },
                    ]}
                />
                {metric.conversion_window_unit !== undefined && (
                    <div className="flex items-center gap-2">
                        <div className="flex items-center gap-2">
                            <LemonInput
                                type="number"
                                className="max-w-20"
                                fullWidth={false}
                                min={intervalBounds[0]}
                                max={intervalBounds[1]}
                                value={metric.conversion_window || 1}
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
                    </div>
                )}
            </div>
        </SceneSection>
    )
}
