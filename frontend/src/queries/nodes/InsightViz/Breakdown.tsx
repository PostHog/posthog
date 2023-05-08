import { useActions, useValues } from 'kea'
import { QueryEditorFilterProps } from '~/types'
import { TaxonomicBreakdownFilterComponent } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function Breakdown({ insightProps }: QueryEditorFilterProps): JSX.Element {
    const { breakdown } = useValues(insightVizDataLogic(insightProps))
    const { updateBreakdown } = useActions(insightVizDataLogic(insightProps))

    return <TaxonomicBreakdownFilterComponent breakdownFilter={breakdown} setFilters={updateBreakdown} />
}
