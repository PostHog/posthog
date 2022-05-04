import { Meta } from '@storybook/react'
import { useMountedLogic } from 'kea'
import React from 'react'
import { mswDecorator } from '~/mocks/browser'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { PersonPropertySelect } from './PersonPropertySelect'

export default {
    title: 'Filters',
    decorators: [
        mswDecorator({
            get: {
                '/api/person/properties': [
                    { name: 'Property A', count: 10 },
                    { name: 'Property B', count: 20 },
                    { name: 'Property C', count: 30 },

                    { name: 'Property D', count: 40 },
                    { name: 'Property E', count: 50 },
                    { name: 'Property F', count: 60 },

                    { name: 'Property G', count: 70 },
                    { name: 'Property H', count: 80 },
                    { name: 'Property I', count: 90 },
                ],
            },
        }),
    ],
} as Meta

export function PersonPropertySelect_(): JSX.Element {
    useMountedLogic(personPropertiesModel)
    const [selectedProperties, setSelectProperties] = React.useState<string[]>([
        '$initial_geoip_postal_code',
        '$initial_geoip_latitude',
        '$initial_geoip_longitude',
        '$geoip_latitude',
        '$geoip_longitude',
        '$geoip_postal_code',
        '$geoip_continent_code',
        '$geoip_continent_name',
        '$initial_geoip_continent_code',
        '$initial_geoip_continent_name',
        '$geoip_time_zone',
        '$geoip_country_code',
        '$geoip_subdivision_1_code',
        '$initial_geoip_subdivision_1_code',
        '$geoip_subdivision_2_code',
        '$initial_geoip_subdivision_2_code',
        '$geoip_subdivision_name',
        '$initial_geoip_subdivision_name',
    ])

    return (
        <PersonPropertySelect selectedProperties={selectedProperties} onChange={setSelectProperties} addText={'Add'} />
    )
}
