import React from 'react'
import { useActions } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { EditorFilterProps } from '~/types'
import { BreakdownFilter } from 'scenes/insights/BreakdownFilter'

export function EFTrendsBreakdown({ filters, insightProps }: EditorFilterProps): JSX.Element {
    const { setFilters } = useActions(trendsLogic(insightProps))

    return <BreakdownFilter filters={filters} setFilters={setFilters} />
}
