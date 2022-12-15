// import { useActions } from 'kea'
// import { trendsLogic } from 'scenes/trends/trendsLogic'
import { LifecycleQuery, InsightQueryNode } from '~/queries/schema'
// import { EditorFilterProps } from '~/types'

import { TestAccountFilter } from './filters/TestAccountFilter'

type LifecycleGlobalFiltersProps = {
    query: LifecycleQuery
    setQuery: (node: LifecycleQuery) => void
}

export function LifecycleGlobalFilters({ query, setQuery }: LifecycleGlobalFiltersProps): JSX.Element {
    // const { setFilters } = useActions(trendsLogic(insightProps))
    return <TestAccountFilter query={query} setQuery={setQuery as (node: InsightQueryNode) => void} />
}
