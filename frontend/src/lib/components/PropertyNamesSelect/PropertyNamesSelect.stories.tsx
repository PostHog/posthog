import React from 'react'
import { mswDecorator } from '~/mocks/browser'
import { PropertyNamesSelect } from './PropertyNamesSelect'
import { useValues } from 'kea'
import { personPropertiesModel } from '~/models/personPropertiesModel'

export default {
    title: 'Filters',
    decorators: [
        mswDecorator({
            get: {
                '/api/person/properties': [
                    { id: 1, name: 'Property A', count: 10 },
                    { id: 2, name: 'Property B', count: 20 },
                    { id: 3, name: 'Property C', count: 30 },

                    { id: 4, name: 'Property D', count: 40 },
                    { id: 5, name: 'Property E', count: 50 },
                    { id: 6, name: 'Property F', count: 60 },

                    { id: 7, name: 'Property G', count: 70 },
                    { id: 8, name: 'Property H', count: 80 },
                    { id: 9, name: 'Property I', count: 90 },
                ],
            },
        }),
    ],
}

export function PropertyNamesSelect_(): JSX.Element {
    const { personProperties } = useValues(personPropertiesModel)
    return (
        <PropertyNamesSelect
            onChange={(selectedProperties) => console.log('Selected Properties', selectedProperties)}
            allProperties={personProperties.map((p) => p.name)}
        />
    )
}
