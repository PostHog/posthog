import { LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export type RetentionMeanType = 'simple' | 'weighted' | null

export function RetentionMeanDropdown(): JSX.Element | null {
    const { insightProps, canEditInsight } = useValues(insightLogic)

    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const showMean = retentionFilter?.showMean || null

    if (!canEditInsight) {
        return null
    }

    return (
        <LemonSelect
            className="w-44"
            size="small"
            value={showMean}
            onChange={(showMean) => {
                updateInsightFilter({ showMean })
            }}
            options={[
                {
                    value: null,
                    labelInMenu: 'No mean calculation',
                    label: 'No mean calculation',
                },
                {
                    value: 'simple',
                    labelInMenu: 'Simple mean',
                    label: 'Simple mean',
                },
                {
                    value: 'weighted',
                    labelInMenu: 'Weighted mean',
                    label: 'Weighted mean',
                },
            ]}
        />
    )
}
