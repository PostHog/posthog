import { LemonCheckbox } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { showValueFilterLogic } from 'lib/components/ShowValueFilter/showValueFilterLogic'

export function ShowValuesFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { showValue } = useValues(showValueFilterLogic(insightProps))
    const { setShowValue } = useActions(showValueFilterLogic(insightProps))

    return (
        <LemonCheckbox
            onChange={setShowValue}
            checked={showValue}
            label={<span className="font-normal">Show values on series</span>}
            bordered
            size="small"
        />
    )
}
