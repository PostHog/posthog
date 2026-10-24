import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'

import { DisplayOptionCheckbox } from '~/queries/nodes/InsightViz/DisplayOptionCheckbox'
import { isFunnelsQuery } from '~/queries/utils'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function HideIncompleteConversionWindowPeriodsFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    if (!isFunnelsQuery(querySource)) {
        return null
    }

    const hideIncompleteConversionWindowPeriods =
        querySource.funnelsFilter?.hideIncompleteConversionWindowPeriods ?? false

    return (
        <DisplayOptionCheckbox
            label="Hide incomplete periods"
            info="Hides recent periods whose conversion window hasn't fully elapsed, so the trend isn't dragged down by entrants who still have time to convert."
            checked={hideIncompleteConversionWindowPeriods}
            onChange={() =>
                updateInsightFilter({
                    hideIncompleteConversionWindowPeriods: !hideIncompleteConversionWindowPeriods,
                })
            }
        />
    )
}
