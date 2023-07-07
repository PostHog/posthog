import { useActions, useValues } from 'kea'
import { EditorFilterProps } from '~/types'
import { TaxonomicBreakdownFilterComponent } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function Breakdown({ insightProps }: EditorFilterProps): JSX.Element {
    const { breakdown, display, isTrends } = useValues(insightVizDataLogic(insightProps))
    const { updateBreakdown, updateDisplay } = useActions(insightVizDataLogic(insightProps))

    return (
        <TaxonomicBreakdownFilterComponent
            breakdownFilter={breakdown}
            display={display}
            isTrends={isTrends}
            updateBreakdown={updateBreakdown}
            updateDisplay={updateDisplay}
            isDataExploration
        />
    )
}
