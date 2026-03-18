import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { EarlyAccessFeature } from 'posthog-js'

import { setFeatureFlags, useStorybookMocks } from '~/mocks/browser'

import { FeaturePreviews } from './FeaturePreviews'

interface StoryProps {
    earlyAccessFeatures: EarlyAccessFeature[]
    enabledFeatureFlags: string[]
}

type Story = StoryObj<(props: StoryProps) => JSX.Element>
const meta: Meta<(props: StoryProps) => JSX.Element> = {
    title: 'Layout/Feature Previews',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta

const Template: StoryFn<StoryProps> = ({ earlyAccessFeatures, enabledFeatureFlags }) => {
    useStorybookMocks({
        get: {
            'https://us.i.posthog.com/api/early_access_features/': { earlyAccessFeatures },
        },
    })
    setFeatureFlags(enabledFeatureFlags)

    return (
        <div className="w-160 p-4 border rounded mx-auto my-2">
            <FeaturePreviews />
        </div>
    )
}

export const Basic: Story = Template.bind({})
Basic.args = {
    earlyAccessFeatures: [
        {
            name: 'Data Warehouse',
            description:
                'The PostHog data warehouse gives you a place to put all of your most important data, query across these datasets, and analyze alongside the product analytics data already in PostHog',
            stage: 'beta',
            documentationUrl: 'https://docs.example.com',
            flagKey: 'data-warehouse',
            payload: {},
        },
    ],
    enabledFeatureFlags: ['data-warehouse'],
}

export const Empty: Story = Template.bind({})
Empty.args = {
    earlyAccessFeatures: [],
    enabledFeatureFlags: [],
}
