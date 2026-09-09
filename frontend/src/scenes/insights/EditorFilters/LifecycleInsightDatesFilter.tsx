import { useActions, useValues } from 'kea'

import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function LifecycleInsightDatesFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { lifecycleFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <LemonCheckbox
            className="p-1 px-2"
            checked={lifecycleFilter?.onlyUseInsightDates ?? false}
            onChange={(checked) => {
                updateInsightFilter({ onlyUseInsightDates: checked })
            }}
            label={<span className="font-normal">Only use insight dates</span>}
            info="Decide who is new from the date range, not from when we first saw the person. Anyone active in the first period counts as new, and activity before the range is ignored."
            size="small"
        />
    )
}
