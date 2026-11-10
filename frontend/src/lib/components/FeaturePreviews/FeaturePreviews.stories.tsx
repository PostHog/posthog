import type { Meta, StoryObj } from '@storybook/react'
import { EarlyAccessFeature } from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'

import { setFeatureFlags, useStorybookMocks } from '~/mocks/browser'

import earlyAccessFeatureDemo from 'public/early-access-feature-demo.png'

import { FeaturePreviews } from './FeaturePreviews'

interface StoryProps {
    earlyAccessFeatures: EarlyAccessFeature[]
    enabledFeatureFlags: string[]
    /** Pins a width close to a scene with the side panel open. */
    narrow?: boolean
}

type Story = StoryObj<(props: StoryProps) => JSX.Element>
const meta: Meta<(props: StoryProps) => JSX.Element> = {
    title: 'Components/Feature Previews',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    render: ({ earlyAccessFeatures, enabledFeatureFlags, narrow }: StoryProps) => {
        useStorybookMocks({
            get: {
                'https://us.i.posthog.com/api/early_access_features/': { earlyAccessFeatures },
            },
        })
        setFeatureFlags(enabledFeatureFlags)

        return (
            <div className={`${narrow ? 'w-120' : 'w-160'} p-4 border rounded mx-auto my-2`}>
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

export const Empty: Story = {
    args: {
        earlyAccessFeatures: [],
        enabledFeatureFlags: [],
    },
}

const QUILL_FEATURES = [
    {
        name: 'Data warehouse',
        description:
            'Put your most important data in one place, query across datasets, and analyze it alongside your product analytics data.',
        stage: 'beta',
        documentationUrl: 'https://docs.example.com',
        flagKey: 'data-warehouse',
        imageUrl: earlyAccessFeatureDemo,
        payload: {},
    },
    {
        name: 'Session summaries',
        description: 'Get a short written summary of each session recording.',
        stage: 'alpha',
        documentationUrl: '',
        flagKey: 'session-summaries',
        payload: {},
    },
] as EarlyAccessFeature[]

export const QuillWithImages: Story = {
    args: {
        earlyAccessFeatures: QUILL_FEATURES,
        enabledFeatureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, 'data-warehouse'],
    },
    parameters: { featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, 'data-warehouse'] },
}

export const QuillNarrow: Story = {
    args: {
        earlyAccessFeatures: QUILL_FEATURES,
        enabledFeatureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, 'data-warehouse'],
        narrow: true,
    },
    parameters: { featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, 'data-warehouse'] },
}
