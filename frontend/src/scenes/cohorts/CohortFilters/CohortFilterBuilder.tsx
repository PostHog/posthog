import { FilterTypes } from 'scenes/cohorts/CohortFilters/types'

interface CohortFilterBuilderProps {
    keys: string[]
    type: FilterTypes
}

export function CohortFilterBuilder({ keys }: CohortFilterBuilderProps): JSX.Element {
    console.log('KEYS', keys)
}
