import './BreakdownTagMenu.scss'

import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonLabel, LemonSwitch } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

export const GlobalBreakdownOptionsMenu = (): JSX.Element => {
    const { insightProps } = useValues(insightLogic)
    const { isTrends } = useValues(insightVizDataLogic(insightProps))

    const { breakdownLimit, breakdownHideOtherAggregation } = useValues(taxonomicBreakdownFilterLogic)
    const { setBreakdownLimit, setBreakdownHideOtherAggregation } = useActions(taxonomicBreakdownFilterLogic)

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
                <LemonInput
                    id="breakdown-limit"
                    min={1}
                    max={1000}
                    value={breakdownLimit}
                    // :HACKY: We cap the breakdown limit in the `onChange` handler, as the `max` prop doesn't enforce anything.
                    onChange={(value) => setBreakdownLimit(value !== undefined ? Math.min(value, 1000) : undefined)}
                    fullWidth={false}
                    className="w-20 ml-2"
                    type="number"
                />
            </div>
        </>
    )
}
