import { useActions } from 'kea'
import { QueryEditorFilterProps } from '~/types'
import { TaxonomicBreakdownFilter } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter'
import { queryNodeToFilter } from '../InsightQuery/utils/queryNodeToFilter'
import { BreakdownFilter as BreakdownFilterType } from '~/queries/schema'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function Breakdown({ insightProps, query }: QueryEditorFilterProps): JSX.Element {
    const { updateBreakdown } = useActions(insightVizDataLogic(insightProps))

    // treat breakdown filter as black box for data exploration for now
    const filters = queryNodeToFilter(query)
    const setFilters = (breakdown: BreakdownFilterType): void => {
        updateBreakdown(breakdown)
    }
    return <TaxonomicBreakdownFilter filters={filters} setFilters={setFilters} />
}
