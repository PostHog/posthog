import './BreakdownTagMenu.scss'

import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonLabel, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

export const MultipleBreakdownsOptionsMenu = (): JSX.Element => {
    const { insightProps } = useValues(insightLogic)
    const { breakdownFilter, isTrends } = useValues(insightVizDataLogic(insightProps))
    const { updateBreakdownFilter } = useActions(insightVizDataLogic(insightProps))

    const { breakdownLimit } = useValues(taxonomicBreakdownFilterLogic)
    const { setBreakdownLimit } = useActions(taxonomicBreakdownFilterLogic)

    return (
        <>
            {isTrends && (
                <LemonSwitch
                    fullWidth
                    className="min-h-10 px-2"
                    checked={!breakdownFilter?.breakdown_hide_other_aggregation}
                    onChange={() =>
                        updateBreakdownFilter({
                            ...breakdownFilter,
                            breakdown_hide_other_aggregation: !breakdownFilter?.breakdown_hide_other_aggregation,
                        })
                    }
                    label={
                        <div className="flex gap-1">
                            <span>Group remaining values under "Other"</span>
                            <Tooltip
                                title={
                                    <>
                                        If you have over {breakdownFilter?.breakdown_limit ?? 25} breakdown options, the
                                        smallest ones are aggregated under the label "Other". Use this toggle to
                                        show/hide the "Other" option.
                                    </>
                                }
                            >
                                <IconInfo className="text-muted text-xl shrink-0" />
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
                    value={breakdownLimit}
                    onChange={(newValue) => {
                        setBreakdownLimit(newValue ?? 25)
                    }}
                    fullWidth={false}
                    className="w-20 ml-2"
                    type="number"
                />
            </div>
        </>
    )
}
