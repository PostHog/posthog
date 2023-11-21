import { Meta, StoryFn } from '@storybook/react'
import { PropertiesTable as PropertiesTableComponent } from '.'
import { PropertyDefinitionType } from '~/types'

const meta: Meta<typeof PropertiesTableComponent> = {
    title: 'Components/Properties Table',
    component: PropertiesTableComponent,
}
export default meta

export const PropertiesTable: StoryFn = () => {
    const properties = {
        name: 'John Doe',
        age: 30,
        url: 'https://www.google.com',
        is_good: true,
        evil_level: null,
        tags: ['best', 'cool', 'awesome'],
        location: {
            city: 'Prague',
            country: 'Czechia',
        },
    }
    return <PropertiesTableComponent type={PropertyDefinitionType.Event} properties={properties} />
}
