import { useActions, useValues } from 'kea'

import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { insightLogic } from '../insightLogic'

export function StackBreakdownFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(trendsDataLogic(insightProps))

    return (
        <LemonCheckbox
            className="p-1 px-2"
            checked={!!trendsFilter?.stackBreakdownValues}
            onChange={(checked) => {
                updateInsightFilter({ stackBreakdownValues: checked })
            }}
            label={<span className="font-normal">Stack breakdown values</span>}
            size="small"
        />
    )
}
