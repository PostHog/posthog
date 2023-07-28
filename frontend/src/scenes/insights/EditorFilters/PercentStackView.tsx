import { useActions, useValues } from 'kea'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { insightLogic } from '../insightLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

export function PercentStackView(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showPercentStackView } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(trendsDataLogic(insightProps))

    return (
        <LemonCheckbox
            checked={!!showPercentStackView}
            onChange={(checked) => {
                updateInsightFilter({ show_percent_stack_view: checked })
            }}
            label={<span className="font-normal">Show as % of total</span>}
            bordered
            size="small"
        />
    )
}
