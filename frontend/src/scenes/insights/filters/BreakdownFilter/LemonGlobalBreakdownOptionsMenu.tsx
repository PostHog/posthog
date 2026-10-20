import './BreakdownTagMenu.scss'

import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonLabel, LemonSwitch } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { MAX_BREAKDOWN_LIMIT, MIN_BREAKDOWN_LIMIT } from './GlobalBreakdownOptionsMenu'
import type { BreakdownOptionsProps } from './GlobalBreakdownOptionsMenu'

export function LemonGlobalBreakdownOptionsMenu({
    isTrends,
    breakdownLimit,
    breakdownHideOtherAggregation,
    setBreakdownHideOtherAggregation,
    onCommitLimit,
}: BreakdownOptionsProps): JSX.Element {
    return (
        <>
            {isTrends && (
                <LemonSwitch
                    fullWidth
                    className="min-h-10 px-2"
                    checked={!breakdownHideOtherAggregation}
                    onChange={() => setBreakdownHideOtherAggregation(!breakdownHideOtherAggregation)}
                    label={
                        <div className="flex gap-1">
                            <span>Group remaining values under "Other"</span>
                            <Tooltip
                                title={
                                    <>
                                        If you have over {breakdownLimit} breakdown options, the smallest ones are
                                        aggregated under the label "Other". Use this toggle to show/hide the "Other"
                                        option.
                                    </>
                                }
                            >
                                <IconInfo className="text-secondary text-xl shrink-0" />
                            </Tooltip>
                        </div>
                    }
                />
            )}
            <div className="px-2 flex gap-2 items-baseline">
                <LemonLabel className="font-medium" htmlFor="breakdown-limit">
                    Breakdown limit
                </LemonLabel>
                {/*
                 * Uncontrolled input so the user can freely clear the field while
                 * retyping. The DOM owns the draft; we only commit to the filter
                 * on blur / Enter. `key={breakdownLimit}` remounts the input when
                 * the committed value changes externally so `defaultValue` stays
                 * in sync.
                 */}
                <LemonInput
                    key={breakdownLimit}
                    id="breakdown-limit"
                    type="number"
                    min={MIN_BREAKDOWN_LIMIT}
                    max={MAX_BREAKDOWN_LIMIT}
                    defaultValue={breakdownLimit}
                    fullWidth={false}
                    className="w-20 ml-2"
                    onBlur={(event) => onCommitLimit(event.currentTarget)}
                    onPressEnter={(event) => event.currentTarget.blur()}
                />
            </div>
        </>
    )
}
