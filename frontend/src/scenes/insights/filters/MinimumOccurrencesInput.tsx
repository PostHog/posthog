import { LemonInput } from '@posthog/lemon-ui'
import { toast } from 'react-toastify'
import { insightLogic } from '../insightLogic'
import { useActions, useValues } from 'kea'
import { retentionLogic } from 'scenes/retention/retentionLogic'

export function MinimumOccurrencesInput(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { retentionFilter } = useValues(retentionLogic(insightProps))
    const { updateInsightFilter } = useActions(retentionLogic(insightProps))
    const { minimumOccurrences = 1 } = retentionFilter || {}

    return (
        <LemonInput
            type="number"
            className="ml-2 w-20"
            defaultValue={minimumOccurrences}
            min={1}
            onBlur={({ target }) => {
                let newValue = Number(target.value)
                if (newValue < 1) {
                    newValue = 1
                    toast.warn(
                        <>
                            The minimum number of occurrences is <strong>1</strong>
                        </>
                    )
                }
                target.value = newValue.toString()
                updateInsightFilter({ minimumOccurrences: newValue })
            }}
        />
    )
}
