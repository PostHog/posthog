import { LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function RetentionReferencePicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const { retention_reference } = retentionFilter || {}

    return (
        <LemonSelect
            className="w-60"
            size="small"
            value={retention_reference || 'total'}
            onChange={(retention_reference) => {
                updateInsightFilter({ retention_reference })
            }}
            options={[
                {
                    value: 'total',
                    labelInMenu: 'Overall cohort',
                    label: '% Overall cohort',
                },
                {
                    value: 'previous',
                    labelInMenu: 'Relative to previous period',
                    label: '% Relative to previous period',
                },
            ]}
        />
    )
}
