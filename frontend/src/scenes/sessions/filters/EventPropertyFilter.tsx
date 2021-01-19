import React from 'react'
import { useActions, useValues } from 'kea'
import { PropertySelect } from 'lib/components/PropertyFilters/PropertySelect'
import { userLogic } from 'scenes/userLogic'
import { EventTypePropertyFilter } from '~/types'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { OperatorValueSelect } from 'lib/components/PropertyFilters/OperatorValueSelect'
import { sessionsFiltersLogic } from 'scenes/sessions/filters/sessionsFiltersLogic'

interface Props {
    filter: EventTypePropertyFilter
    selector: number
}

export function EventPropertyFilter({ filter, selector }: Props): JSX.Element {
    const { eventProperties } = useValues(userLogic)
    const { updateFilter } = useActions(sessionsFiltersLogic)

    const property = filter.properties && filter.properties.length > 0 ? filter.properties[0] : null
    const value = property
        ? { value: property.key, label: keyMapping.event[property.key]?.label || property.key }
        : null

    return (
        <>
            <PropertySelect
                value={value}
                optionGroups={[
                    {
                        type: 'event',
                        label: 'Event properties',
                        options: eventProperties,
                    },
                ]}
                onChange={(_, key) => {
                    updateFilter(
                        {
                            ...filter,
                            properties: [{ operator: 'exact', value: null, ...property, type: 'event', key }],
                        },
                        selector
                    )
                }}
                placeholder="Add property filter"
            />
            {property && (
                <OperatorValueSelect
                    type="event"
                    propkey={property.key}
                    operator={property.operator}
                    value={property.value}
                    onChange={(operator, value) => {
                        updateFilter(
                            {
                                ...filter,
                                properties: [{ ...property, operator, value }],
                            },
                            selector
                        )
                    }}
                />
            )}
        </>
    )
}
