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
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud' },
                '/stats': {},
                '/events': {},
            },
            patch: {
                '/api/environments/:team_id/add_product_intent/': {},
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const Default: Story = {
    render: () => {
        useDelayedOnMountEffect(() => {
            router.actions.push(urls.onboardingWelcome())
        })
        return <App />
    },
    parameters: {
        testOptions: { waitForSelector: '[data-attr="sdk-continue"]' },
    },
}

// A user on the simple onboarding arm with a new project, so the sidebar also links to this page. Data
// warehouse has no install step of its own, so its steps follow the Wizard install.
export const ProductSelected: Story = {
    render: () => {
        const { loadCurrentTeamSuccess } = useActions(teamLogic)
        useDelayedOnMountEffect(() => {
            loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, created_at: '2023-05-23T00:00:00Z' })
            router.actions.push(urls.onboardingWelcome(), { product: ProductKey.DATA_WAREHOUSE })
        })
        return <App />
    },
    parameters: {
        featureFlags: { [FEATURE_FLAGS.ONBOARDING_SIMPLE_FLOW]: 'test' },
        testOptions: { waitForSelector: '[data-attr="sdk-continue"]' },
    },
}
