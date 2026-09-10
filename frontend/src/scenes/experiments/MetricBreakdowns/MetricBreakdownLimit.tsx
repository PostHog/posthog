import { IconInfo } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { ExperimentMetric } from '~/queries/schema/schema-general'

const DEFAULT_BREAKDOWN_LIMIT = 25
/**
 * The backend has no unlimited option, so "Show all" is just a large top-N that covers any
 * realistic breakdown cardinality.
 */
const SHOW_ALL_BREAKDOWN_LIMIT = 1000

const BREAKDOWN_LIMIT_OPTIONS = [
    { value: 5, label: '5' },
    { value: 10, label: '10' },
    { value: 15, label: '15' },
    { value: 20, label: '20' },
    { value: 25, label: '25' },
    { value: SHOW_ALL_BREAKDOWN_LIMIT, label: 'Show all' },
]

export function MetricBreakdownLimit({
    metric,
    onChange,
}: {
    metric: ExperimentMetric
    onChange: (breakdownLimit: number) => void
}): JSX.Element {
    const breakdownLimit = metric.breakdownFilter?.breakdown_limit ?? DEFAULT_BREAKDOWN_LIMIT

    /**
     * This is a protection against manual edits of the metric breakdown limit, in case
     * a limit is set that does not map to a preset.
     */
    const options = BREAKDOWN_LIMIT_OPTIONS.some(({ value }) => value === breakdownLimit)
        ? BREAKDOWN_LIMIT_OPTIONS
        : [{ value: breakdownLimit, label: String(breakdownLimit) }, ...BREAKDOWN_LIMIT_OPTIONS]

    return (
        <div className="flex items-center gap-1">
            <span className="text-muted">Limit</span>
            <Tooltip
                title={
                    <>
                        Keeps only the top breakdown values by frequency. The remaining values are grouped together
                        under "Other". This caps how many breakdown rows the results show. "Show all" raises the cap
                        high enough to cover any realistic number of values.
                    </>
                }
            >
                <IconInfo className="text-secondary text-base shrink-0" />
            </Tooltip>
            <LemonSelect
                size="small"
                value={breakdownLimit}
                options={options}
                onChange={(value) => {
                    if (value != null && value !== breakdownLimit) {
                        onChange(value)
                    }
                }}
                dropdownMatchSelectWidth={false}
                data-attr="experiment-breakdown-limit"
            />
        </div>
    )
}
