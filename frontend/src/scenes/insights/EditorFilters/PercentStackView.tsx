import { useActions, useValues } from 'kea'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { insightLogic } from '../insightLogic'
import { percentStackViewLogic } from './percentStackViewLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

export function PercentStackView(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showPercentStackView } = useValues(trendsDataLogic(insightProps))
    const { setShowPercentStackView } = useActions(percentStackViewLogic(insightProps))

    return (
        <LemonCheckbox
            checked={showPercentStackView}
            onChange={setShowPercentStackView}
            label={<span className="font-normal">Show 100% Stacked</span>}
            bordered
            size="small"
        />
    )
}
