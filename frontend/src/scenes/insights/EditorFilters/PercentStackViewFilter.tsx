import { useActions, useValues } from 'kea'

import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { insightLogic } from '../insightLogic'
import { insightVizDataLogic } from '../insightVizDataLogic'

export function PercentStackViewFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showPercentStackView } = useValues(trendsDataLogic(insightProps))
    const { isSingleSeriesOutput } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(trendsDataLogic(insightProps))

    // One value per point always stacks to 100%, so the chart flattens. Still let the user turn the
    // option off when a saved insight already has it on.
    const disabledReason =
        isSingleSeriesOutput && !showPercentStackView
            ? 'Add another series or a breakdown to compare each share of the total'
            : undefined

    return (
        <LemonCheckbox
            className="p-1 px-2"
            checked={!!showPercentStackView}
            onChange={(checked) => {
                updateInsightFilter({ showPercentStackView: checked })
            }}
            label={<span className="font-normal">Show as % of total</span>}
            size="small"
            disabledReason={disabledReason}
        />
    )
}
