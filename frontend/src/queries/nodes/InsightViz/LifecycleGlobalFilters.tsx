import { LifecycleQuery, InsightQueryNode } from '~/queries/schema'

import { TestAccountFilter } from './filters/TestAccountFilter'

type LifecycleGlobalFiltersProps = {
    query: LifecycleQuery
    setQuery: (node: LifecycleQuery) => void
}

export function LifecycleGlobalFilters({ query, setQuery }: LifecycleGlobalFiltersProps): JSX.Element {
    return <TestAccountFilter query={query} setQuery={setQuery as (node: InsightQueryNode) => void} />
}
