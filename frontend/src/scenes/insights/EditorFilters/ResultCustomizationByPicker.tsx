import { LemonSegmentedButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'

import { ResultCustomizationBy } from '~/queries/schema/schema-general'

import { insightVizDataLogic } from '../insightVizDataLogic'

export const RESULT_CUSTOMIZATION_DEFAULT = ResultCustomizationBy.Value

export function ResultCustomizationByPicker(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { resultCustomizationBy } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <LemonSegmentedButton
            className="pb-2 px-2"
            onChange={(value) => updateInsightFilter({ resultCustomizationBy: value as ResultCustomizationBy })}
            value={resultCustomizationBy || RESULT_CUSTOMIZATION_DEFAULT}
            options={[
                { value: ResultCustomizationBy.Value, label: 'By name' },
                { value: ResultCustomizationBy.Position, label: 'By rank' },
            ]}
            size="small"
            fullWidth
        />
    )
}
