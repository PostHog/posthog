import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'

import { insightVizDataLogic } from '../insightVizDataLogic'
import { InsightDisplayToggle, InsightToggleVariant } from './InsightDisplayToggle'

export function ShowAnnotationsFilter({ variant }: { variant?: InsightToggleVariant } = {}): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { showAnnotations } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const checked = showAnnotations !== false

    return (
        <InsightDisplayToggle
            label="Show annotations"
            onChange={(value) => updateInsightFilter({ showAnnotations: value })}
            checked={checked}
            variant={variant}
        />
    )
}
