import type { Meta, StoryObj } from '@storybook/react'
import { EarlyAccessFeature } from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'

import { setFeatureFlags, useStorybookMocks } from '~/mocks/browser'

import blankDashboardHog from 'public/blank-dashboard-hog.png'
import earlyAccessFeatureDemo from 'public/early-access-feature-demo.png'
import selfDrivingHog from 'public/hedgehog/self-driving-hog.png'

import { FeaturePreviews, FeaturePreviewsComingSoon } from './FeaturePreviews'

interface StoryProps {
    earlyAccessFeatures: EarlyAccessFeature[]
    enabledFeatureFlags: string[]
    width?: 'narrow' | 'wide'
    comingSoon?: boolean
}

type Story = StoryObj<(props: StoryProps) => JSX.Element>
const meta: Meta<(props: StoryProps) => JSX.Element> = {
    title: 'Components/Feature Previews',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    render: ({ earlyAccessFeatures, enabledFeatureFlags, width, comingSoon }: StoryProps) => {
        useStorybookMocks({
            get: {
                'https://us.i.posthog.com/api/early_access_features/': { earlyAccessFeatures },
            },
        })
        setFeatureFlags(enabledFeatureFlags)

        return (
            <div
                className={`${width === 'narrow' ? 'w-120' : width === 'wide' ? 'w-240' : 'w-160'} p-4 border rounded mx-auto my-2`}
            >
                {comingSoon ? <FeaturePreviewsComingSoon /> : <FeaturePreviews />}
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
        name: 'Dashboard templates',
        description: 'Start a dashboard from a template that fits your product.',
        stage: 'beta',
        documentationUrl: '',
        flagKey: 'dashboard-templates',
        imageUrl: blankDashboardHog,
        payload: {},
    },
    {
        name: 'Vim mode for SQL editor',
        description: 'Edit SQL with Vim key bindings.',
        stage: 'beta',
        documentationUrl: '',
        flagKey: 'sql-vim-mode',
        payload: {},
    },
    {
        name: 'Session summaries',
        description: 'Get a short written summary of each session recording.',
        stage: 'alpha',
        documentationUrl: '',
        flagKey: 'session-summaries',
        imageUrl: selfDrivingHog,
        payload: {},
    },
    {
        name: 'Metrics',
        description: 'Send time-series metrics from your services and see them next to your events, replays, and logs.',
        stage: 'alpha',
        documentationUrl: 'https://docs.example.com',
        flagKey: 'metrics',
        payload: {},
    },
    {
        name: 'Mobile heatmaps',
        description: 'See where people tap in your iOS and Android apps.',
        stage: 'concept',
        documentationUrl: '',
        flagKey: 'mobile-heatmaps',
        payload: {},
    },
    {
        name: 'Revenue alerts',
        description: 'Get a message when revenue goes up or down more than you expect.',
        stage: 'concept',
        documentationUrl: '',
        flagKey: 'revenue-alerts',
        payload: {},
    },
] as EarlyAccessFeature[]

const QUILL_FLAGS = [FEATURE_FLAGS.TODAY_RAIL_NAV, 'data-warehouse', 'metrics']

export const QuillWithImages: Story = {
    args: { earlyAccessFeatures: QUILL_FEATURES, enabledFeatureFlags: QUILL_FLAGS, width: 'wide' },
    parameters: { featureFlags: QUILL_FLAGS },
}

export const QuillNarrow: Story = {
    args: { earlyAccessFeatures: QUILL_FEATURES, enabledFeatureFlags: QUILL_FLAGS, width: 'narrow' },
    parameters: { featureFlags: QUILL_FLAGS },
}

export const QuillComingSoon: Story = {
    args: { earlyAccessFeatures: QUILL_FEATURES, enabledFeatureFlags: QUILL_FLAGS, width: 'wide', comingSoon: true },
    parameters: { featureFlags: QUILL_FLAGS },
}
