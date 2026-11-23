import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'

import { AnyPropertyFilter } from '~/types'

import type { TaggerConditionApi } from '../generated/api.schemas'

export function TaggerConditionRow({
    condition,
    index,
}: {
    condition: TaggerConditionApi
    index: number
}): JSX.Element {
    const properties = (condition.properties ?? []) as AnyPropertyFilter[]
    return (
        <div className="border rounded p-3 space-y-2">
            <div className="text-sm">
                {index > 0 && <span className="text-muted">OR </span>}
                {condition.rollout_percentage ?? 100}% of generations
                {properties.length > 0 && ' matching:'}
            </div>
            {properties.length > 0 && <PropertyFiltersDisplay filters={properties} compact />}
        </div>
    )
}
