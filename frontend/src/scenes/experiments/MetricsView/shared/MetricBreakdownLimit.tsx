import { IconInfo } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { ExperimentMetric } from '~/queries/schema/schema-general'

const DEFAULT_BREAKDOWN_LIMIT = 25
// "Show all" has no true unlimited on the backend; the max clamp (1000) is effectively all.
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

    // A metric may carry a non-preset limit (e.g. set elsewhere); surface it so the
    // dropdown always reflects the current value instead of falling back to a placeholder.
    const options = BREAKDOWN_LIMIT_OPTIONS.some((o) => o.value === breakdownLimit)
        ? BREAKDOWN_LIMIT_OPTIONS
        : [{ value: breakdownLimit, label: String(breakdownLimit) }, ...BREAKDOWN_LIMIT_OPTIONS]

    return (
        <div className="flex items-center gap-1">
            <span className="text-muted">Limit</span>
            <Tooltip
                title={
                    <>
                        Keeps only the top breakdown values by frequency. The remaining values are grouped together
                        under "Other". This caps how many breakdown rows the results show. "Show all" raises the cap to
                        the maximum.
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
