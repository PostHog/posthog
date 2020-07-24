import React from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { SessionFilter } from 'lib/components/SessionsFilter'
import { ViewType } from '../insightLogic'
import { trendsLogic } from '../trendsLogic'

export function SessionTab(): JSX.Element {
    const { filters } = useValues(trendsLogic({ dashboardItemId: null, view: ViewType.SESSIONS }))
    const { setFilters } = useActions(trendsLogic({ dashboardItemId: null, view: ViewType.SESSIONS }))

    return (
        <>
            <h4 className="secondary">{'Type'}</h4>
            <SessionFilter value={filters.session} onChange={(v): void => setFilters({ session: v })} />
            <hr />
            <h4 className="secondary">Filters</h4>
            <PropertyFilters pageKey="trends-sessions" />
        </>
    )
}
