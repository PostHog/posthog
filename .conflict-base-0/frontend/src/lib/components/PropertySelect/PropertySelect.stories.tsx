import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { mswDecorator } from '~/mocks/browser'

import { TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
import { PropertySelect, PropertySelectProps } from './PropertySelect'

type Story = StoryObj<typeof PropertySelect>
const meta: Meta<typeof PropertySelect> = {
    title: 'Filters/Property Select',
    component: PropertySelect,
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/persons/properties': [
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
}
export default meta

const Template: StoryFn<typeof PropertySelect> = (props: Partial<PropertySelectProps>) => {
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
        <PropertySelect
            selectedProperties={selectedProperties}
            onChange={setSelectProperties}
            taxonomicFilterGroup={TaxonomicFilterGroupType.PersonProperties}
            addText="Add"
            {...props}
        />
    )
}

export const Default: Story = Template.bind({})
Default.args = {}

export const Sortable: Story = Template.bind({})
Sortable.args = {
    sortable: true,
}
