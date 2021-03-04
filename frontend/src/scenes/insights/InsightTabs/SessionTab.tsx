import React from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { SessionFilter } from 'lib/components/SessionsFilter'
import { ViewType } from '../insightLogic'
import { trendsLogic } from '../../trends/trendsLogic'
import { ActionFilter } from '../ActionFilter/ActionFilter'
import { FilterType } from '~/types'

export function SessionTab(): JSX.Element {
    const { filters } = useValues(trendsLogic({ dashboardItemId: null, view: ViewType.SESSIONS }))
    const { setFilters } = useActions(trendsLogic({ dashboardItemId: null, view: ViewType.SESSIONS }))

    return (
        <>
            <h4 className="secondary">{'Actions & Events'}</h4>
            <ActionFilter
                filters={filters}
                setFilters={(payload: Partial<FilterType>): void => setFilters(payload)}
                typeKey={'sessions' + ViewType.SESSIONS}
                hideMathSelector={true}
                copy="Add action or event"
            />
            <hr />
            <h4 className="secondary">{'Type'}</h4>
            <SessionFilter value={filters.session} onChange={(v: string): void => setFilters({ session: v })} />
            <hr />
            <h4 className="secondary">Filters</h4>
            <PropertyFilters pageKey="trends-sessions" />
        </>
    )
}
