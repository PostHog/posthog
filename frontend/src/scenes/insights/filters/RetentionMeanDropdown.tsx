import { LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { RETENTION_MEAN_NONE } from 'lib/constants'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export type RetentionMeanType = 'simple' | 'weighted' | typeof RETENTION_MEAN_NONE

export function RetentionMeanDropdown(): JSX.Element | null {
    const { insightProps, canEditInsight } = useValues(insightLogic)

    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const showMean = retentionFilter?.showMean || RETENTION_MEAN_NONE

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
                    value: RETENTION_MEAN_NONE,
                    labelInMenu: 'No mean calculation',
                    label: 'No mean calculation',
                },
                {
                    value: 'simple',
                    labelInMenu: 'Simple mean',
                    label: 'Simple mean',
                    tooltip:
                        'Calculates the average retention rate across all cohorts by giving equal weight to each cohort, regardless of its size.',
                },
                {
                    value: 'weighted',
                    labelInMenu: 'Weighted mean',
                    label: 'Weighted mean',
                    tooltip:
                        'Calculates the average retention rate by giving more weight to larger cohorts, accounting for different cohort sizes in the final mean.',
                },
            ]}
        />
    )
}
