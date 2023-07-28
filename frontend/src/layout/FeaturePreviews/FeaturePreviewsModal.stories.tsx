import { Meta, StoryFn } from '@storybook/react'
import { FeaturePreviewsModal as FeaturePreviewsModalComponent } from './FeaturePreviewsModal'
import { useFeatureFlags, useStorybookMocks } from '~/mocks/browser'
import { EarlyAccessFeature } from 'posthog-js'
import { CONSTRAINED_PREVIEWS } from './featurePreviewsLogic'
import { FeatureFlagKey } from 'lib/constants'

export default {
    title: 'Layout/Feature Previews Modal',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',
    },
} as Meta

CONSTRAINED_PREVIEWS.add('constrained-test-1' as FeatureFlagKey)
CONSTRAINED_PREVIEWS.add('constrained-test-2' as FeatureFlagKey)

const Template: StoryFn<{ earlyAccessFeatures: EarlyAccessFeature[]; enabledFeatureFlags: string[] }> = ({
    earlyAccessFeatures,
    enabledFeatureFlags,
}) => {
    useStorybookMocks({
        get: {
            'https://app.posthog.com/api/early_access_features/': { earlyAccessFeatures },
        },
    })
    useFeatureFlags(enabledFeatureFlags)

    return (
        <div className="bg-default p-2">
            <FeaturePreviewsModalComponent inline />
        </div>
    )
}

export const Basic = Template.bind({})
Basic.args = {
    earlyAccessFeatures: [
        {
            name: 'Data Warehouse',
            description:
                'The PostHog data warehouse gives you a place to put all of your most important data, query across these datasets, and analyze alongside the product analytics data already in PostHog',
            stage: 'beta',
            documentationUrl: 'https://docs.example.com',
            flagKey: 'data-warehouse',
        },
    ],
    enabledFeatureFlags: ['data-warehouse'],
}

export const WithConstrainedFeature = Template.bind({})
WithConstrainedFeature.args = {
    earlyAccessFeatures: [
        {
            name: 'Constrained Test 1', // Only presented if constrained-test-1-preview is enabled
            description: '',
            stage: 'beta',
            documentationUrl: '',
            flagKey: 'constrained-test-1',
        },
        {
            name: 'Constrained Test 2', // Only presented if constrained-test-2-preview is enabled
            description: '',
            stage: 'beta',
            documentationUrl: '',
            flagKey: 'constrained-test-2',
        },
        {
            name: 'Data Warehouse',
            description:
                'The PostHog data warehouse gives you a place to put all of your most important data, query across these datasets, and analyze alongside the product analytics data already in PostHog',
            stage: 'beta',
            documentationUrl: 'https://docs.example.com',
            flagKey: 'data-warehouse',
        },
    ],
    enabledFeatureFlags: ['constrained-test-1-preview', 'constrained-test-1', 'constrained-test-2'],
}

export const Empty = Template.bind({})
Empty.args = {
    earlyAccessFeatures: [],
    enabledFeatureFlags: [],
}
