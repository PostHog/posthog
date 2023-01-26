import { ComponentMeta, ComponentStory } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useState } from 'react'
import { mswDecorator } from '~/mocks/browser'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { PersonPropertySelect, PersonPropertySelectProps } from './PersonPropertySelect'

export default {
    title: 'Filters/Person Property Select',
    component: PersonPropertySelect,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/persons/properties': [
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
    parameters: {
        chromatic: { disableSnapshot: false },
    },
} as ComponentMeta<typeof PersonPropertySelect>

const Template: ComponentStory<typeof PersonPropertySelect> = (props: Partial<PersonPropertySelectProps>) => {
    useMountedLogic(personPropertiesModel)
    const [selectedProperties, setSelectProperties] = useState<string[]>([
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
        <PersonPropertySelect
            selectedProperties={selectedProperties}
            onChange={setSelectProperties}
            addText="Add"
            {...props}
        />
    )
}

export const Default = Template.bind({})
Default.args = {}

export const Sortable = Template.bind({})
Sortable.args = {
    sortable: true,
}
