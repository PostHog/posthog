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

export const ExternalSourceProperties: Story = {
    render: () => {
        const properties = {
            'eas/account': 'pineapple-labs',
            'eas/build_id': '2f9a1c74-6f0b-4a4e-9a1e-8c2b7d5f0a31',
            'eas/channel': 'production',
            'eas/project_id': 'c81b3d02-77e4-4b6a-9f3e-1d0a5c8b2467',
            'eas/runtime_version': '1.4.0',
            'eas/update_id': '7d4e9b18-3c52-4f8a-b0d6-9e1f2a7c4b85',
            'eas/workflow_id': 'a3c6f291-58d7-4e0b-8c4a-6b2d9f13e057',
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
