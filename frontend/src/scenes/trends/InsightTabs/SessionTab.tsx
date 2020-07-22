import React from 'react'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { SessionFilter } from 'lib/components/SessionsFilter'

interface Props {
    filters: Record<string, unknown>
    onChange: (v: string) => void
}

export function SessionTab(props: Props): JSX.Element {
    const { filters, onChange } = props

    return (
        <>
            <SessionFilter value={filters.session} onChange={(v): void => onChange(v)} />
            <hr />
            <h4 className="secondary">Filters</h4>
            <PropertyFilters pageKey="trends-sessions" />
        </>
    )
}
