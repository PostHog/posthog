import React from 'react'
import { useActions } from 'kea'
import { PersonPropertyFilter } from '~/types'
import { OperatorValueSelect } from 'lib/components/PropertyFilters/OperatorValueSelect'
import { sessionsFiltersLogic } from 'scenes/sessions/filters/sessionsFiltersLogic'

interface Props {
    filter: PersonPropertyFilter
    selector: number
}

export function PersonFilter({ filter, selector }: Props): JSX.Element {
    const { updateFilter } = useActions(sessionsFiltersLogic)

    return (
        <OperatorValueSelect
            type="person"
            propkey={filter.key}
            operator={filter.operator}
            value={filter.value}
            onChange={(operator, value) => {
                updateFilter({ ...filter, operator, value }, selector)
            }}
        />
    )
}
