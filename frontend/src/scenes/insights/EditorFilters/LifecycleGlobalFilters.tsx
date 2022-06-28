import React from 'react'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'
import { useActions } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { EditorFilterProps } from '~/types'

export function LifecycleGlobalFilters({ filters, insightProps }: EditorFilterProps): JSX.Element {
    const { setFilters } = useActions(trendsLogic(insightProps))
    return <TestAccountFilter filters={filters} onChange={setFilters} />
}
