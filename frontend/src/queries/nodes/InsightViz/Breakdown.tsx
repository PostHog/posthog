import { useActions, useValues } from 'kea'
import { EditorFilterProps } from '~/types'
import { TaxonomicBreakdownFilter } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter'
import { insightVizLogic } from 'scenes/insights/insightVizLogic'

export function Breakdown({ insightProps }: EditorFilterProps): JSX.Element {
    const { breakdown, display, isTrends } = useValues(insightVizLogic(insightProps))
    const { updateBreakdown, updateDisplay } = useActions(insightVizLogic(insightProps))

    return (
        <TaxonomicBreakdownFilter
            breakdownFilter={breakdown}
            display={display}
            isTrends={isTrends}
            updateBreakdown={updateBreakdown}
            updateDisplay={updateDisplay}
        />
    )
}
