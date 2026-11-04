import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { ProductKey } from '~/queries/schema/schema-general'

const meta: Meta = {
    title: 'Scenes-Other/Onboarding/Welcome',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
        // Setup screens show a "listening for data" spinner and an animated preview by design.
        testOptions: { waitForLoadersToDisappear: false },
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud' },
                '/stats': {},
                '/events': {},
                '/api/projects/:team_id/insights/': { count: 0, results: [] },
                '/api/projects/:team_id/event_definitions/': { count: 0, results: [] },
                '/api/environments/:team_id/session_recordings': {
                    results: [{ id: 'example-recording' }],
                    has_next: false,
                },
            },
            patch: {
                '/api/environments/:team_id/add_product_intent/': {},
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

function welcomeStory(productKey: ProductKey | undefined, waitForSelector: string): Story {
    return {
        render: () => {
            const { loadCurrentTeamSuccess } = useActions(teamLogic)
            useDelayedOnMountEffect(() => {
                loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, created_at: '2023-05-23T00:00:00Z' })
                router.actions.push(urls.onboardingWelcome(), productKey ? { product: productKey } : undefined)
            })
            return <App />
        },
        parameters: {
            featureFlags: { [FEATURE_FLAGS.ONBOARDING_SIMPLE_FLOW]: 'test' },
            testOptions: { waitForSelector },
        },
    }
}

export const Default: Story = welcomeStory(undefined, '[data-attr="onboarding-welcome-ai-prompt"]')

/** No saved insights yet, so product analytics shows its own setup screen under the Wizard callout. */
export const ProductNeedsSetup: Story = welcomeStory(ProductKey.PRODUCT_ANALYTICS, '[data-attr="product-empty-state"]')

/** Recordings exist, so session replay reads as set up, with what to try first and a link in. */
export const ProductInstalled: Story = welcomeStory(
    ProductKey.SESSION_REPLAY,
    '[data-attr="onboarding-welcome-product-ready"]'
)
