import { funnelConversionRate } from '@posthog/quill-charts'

import { IconTrendingFlat, IconTrendingFlatDown } from 'lib/lemon-ui/icons'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

/** One cell of the per-step legend below the plot, pixel-aligned under that step's bars. */
export function StepFooterCell({
    stepIndex,
    steps,
    stepTotals,
}: {
    stepIndex: number
    steps: string[]
    stepTotals: number[]
}): JSX.Element {
    const label = steps[stepIndex]
    const count = stepTotals[stepIndex]
    const previousCount = stepIndex > 0 ? stepTotals[stepIndex - 1] : null
    const droppedOff = previousCount != null ? Math.max(previousCount - count, 0) : 0
    const droppedOffRate = previousCount ? 1 - funnelConversionRate(count, previousCount) : 0
    return (
        <div className="flex flex-col gap-1 px-1 py-2 text-xs">
            <div className="flex items-center gap-1.5 font-medium">
                <Lettermark name={stepIndex + 1} color={LettermarkColor.Gray} />
                <span className="truncate" title={label}>
                    {label}
                </span>
            </div>
            <Tooltip title="Users who completed this step, with conversion rate relative to the first step">
                <div className="flex items-center gap-1.5">
                    <IconTrendingFlat className="text-success shrink-0" />
                    <span>
                        {pluralize(count, 'user')}{' '}
                        <span className="text-secondary">
                            ({percentage(funnelConversionRate(count, stepTotals[0]), 2)})
                        </span>
                    </span>
                </div>
            </Tooltip>
            {previousCount != null && (
                <Tooltip title="Users who didn't complete this step, with drop-off rate relative to the previous step">
                    <div className="flex items-center gap-1.5">
                        <IconTrendingFlatDown className="text-danger shrink-0" />
                        <span>
                            {pluralize(droppedOff, 'user')}{' '}
                            <span className="text-secondary">({percentage(droppedOffRate, 2)})</span>
                        </span>
                    </div>
                </Tooltip>
            )}
        </div>
    )
}
