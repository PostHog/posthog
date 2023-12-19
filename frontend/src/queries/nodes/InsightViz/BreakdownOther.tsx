import { useActions, useValues } from 'kea'
import { IconInfo } from 'lib/lemon-ui/icons'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { EditorFilterProps } from '~/types'

export function BreakdownOther({ insightProps }: EditorFilterProps): JSX.Element | null {
    const { breakdown } = useValues(insightVizDataLogic(insightProps))
    const { updateBreakdown } = useActions(insightVizDataLogic(insightProps))

    return breakdown ? (
        <LemonSwitch
            bordered
            fullWidth
            checked={!breakdown.breakdown_hide_other_aggregation}
            onChange={() =>
                updateBreakdown({
                    ...breakdown,
                    breakdown_hide_other_aggregation: !breakdown.breakdown_hide_other_aggregation,
                })
            }
            label={
                <div className="flex gap-1">
                    <span>Group remaining values under "Other"</span>
                    <Tooltip
                        title={
                            <>
                                If you have over {breakdown.breakdown_limit ?? 25} breakdown options, the smallest ones
                                are aggregated under the label "Other". Use this toggle to show/hide the "Other" option.
                            </>
                        }
                    >
                        <IconInfo className="text-muted text-xl shrink-0" />
                    </Tooltip>
                </div>
            }
        />
    ) : null
}
