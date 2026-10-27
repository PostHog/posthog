import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'

import { DisplayOptionCheckbox } from '~/queries/nodes/InsightViz/DisplayOptionCheckbox'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function ShowLegendFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { showLegend } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const toggleShowLegend = (): void => {
        updateInsightFilter({ showLegend: !showLegend })
    }

    return <DisplayOptionCheckbox label="Show legend" checked={!!showLegend} onChange={toggleShowLegend} />
}
