import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'

import { PropertyDefinitionType } from '~/types'

import { PropertiesTable as PropertiesTableComponent } from '.'
import { PropertiesTableProps } from './PropertiesTable'

const meta: Meta<PropertiesTableProps> = {
    title: 'Components/Properties Table',
    component: PropertiesTableComponent,
}
type Story = StoryObj<PropertiesTableProps>
export default meta

export const Basic: Story = {
    render: () => {
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
    },
}

export const DollarPropertiesOnEvent: Story = {
    render: () => {
        const properties = {
            pineapple_enjoyment_score: 3,
            $browser: 'Chrome',
            utm_campaign: 'summer_sale',
            $geoip_country_code: 'US',
            $set: {
                $browser: 'Chrome',
                utm_campaign: 'summer_sale',
                $geoip_country_code: 'US',
            },
            $set_once: {
                $initial_browser: 'Chrome',
                $initial_utm_campaign: 'summer_sale',
                $initial_geoip_country_code: 'US',
            },
        }
        return <PropertiesTableComponent type={PropertyDefinitionType.Event} properties={properties} />
    },
}

export const DollarPropertiesOnPersonSearchable: Story = {
    render: () => {
        const properties = {
            pineapple_enjoyment_score: 3,
            $browser: 'Chrome',
            utm_campaign: 'summer_sale',
            $geoip_country_code: 'US',
            $initial_browser: 'Chrome',
            $initial_utm_campaign: 'summer_sale',
            $initial_geoip_country_code: 'US',
        }
        return <PropertiesTableComponent type={PropertyDefinitionType.Person} properties={properties} searchable />
    },
}

export const DollarPropertiesOnPersonHidden: Story = {
    render: () => {
        const { setHidePostHogPropertiesInTable } = useActions(userPreferencesLogic)

        useDelayedOnMountEffect(() => setHidePostHogPropertiesInTable(true))

        const properties = {
            pineapple_enjoyment_score: 3,
            $browser: 'Chrome',
            utm_campaign: 'summer_sale',
            $geoip_country_code: 'US',
            $initial_browser: 'Chrome',
            $initial_utm_campaign: 'summer_sale',
            $initial_geoip_country_code: 'US',
        }
        return (
            <PropertiesTableComponent
                type={PropertyDefinitionType.Person}
                properties={properties}
                searchable
                filterable
            />
        )
    },
}
