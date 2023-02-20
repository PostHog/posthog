import { LemonCheckbox } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { showValueFilterLogic } from 'lib/components/ShowValueFilter/showValueFilterLogic'

export function ShowValuesFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { showValue, disabled } = useValues(showValueFilterLogic(insightProps))
    const { setShowValue } = useActions(showValueFilterLogic(insightProps))

    // Hide show values filter control when disabled to avoid states where control is "disabled but checked"
    if (disabled) {
        return null
    }

    return (
        <LemonCheckbox
            onChange={setShowValue}
            checked={showValue}
            disabled={disabled}
            label={<span className="font-normal">Show values on series</span>}
            bordered
            size="small"
        />
    )
}
