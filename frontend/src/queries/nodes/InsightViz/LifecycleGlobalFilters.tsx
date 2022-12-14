import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'
import { useActions } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { EditorFilterProps } from '~/types'

// type LifecycleGlobalFiltersProps = {
//     // query: // query.source? // InsightQueryNode or LifecycleQuery
//     // setQuery: // query.setQuerySource?
// }

export function LifecycleGlobalFilters({ filters, insightProps }: EditorFilterProps): JSX.Element {
    const { setFilters } = useActions(trendsLogic(insightProps))
    // insightVizLogic

    return <TestAccountFilter filters={filters} onChange={setFilters} />
}
