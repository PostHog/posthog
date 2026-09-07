import type { Meta, StoryObj } from '@storybook/react'
import { EarlyAccessFeature } from 'posthog-js'

import { setFeatureFlags, useStorybookMocks } from '~/mocks/browser'

import { FeaturePreviews } from './FeaturePreviews'

interface StoryProps {
    earlyAccessFeatures: EarlyAccessFeature[]
    enabledFeatureFlags: string[]
}

type Story = StoryObj<(props: StoryProps) => JSX.Element>
const meta: Meta<(props: StoryProps) => JSX.Element> = {
    title: 'Components/Feature Previews',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    render: ({ earlyAccessFeatures, enabledFeatureFlags }: StoryProps) => {
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
    },
}
export default meta

export const Basic: Story = {
    args: {
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
    },
}

// PostHog Desktop is a public download, so its switch grants nothing on its own — the card
// promotes the download instead of implying the switch unlocks the app.
export const DownloadableApp: Story = {
    args: {
        earlyAccessFeatures: [
            {
                name: 'PostHog Desktop',
                description: 'An agentic development environment giving coding agents access to product context',
                stage: 'beta',
                documentationUrl: 'https://posthog.com/docs/posthog-desktop/download-posthog-desktop',
                flagKey: 'twig',
                payload: {},
            },
        ],
        enabledFeatureFlags: ['twig'],
    },
}

export const Empty: Story = {
    args: {
        earlyAccessFeatures: [],
        enabledFeatureFlags: [],
    },
}
