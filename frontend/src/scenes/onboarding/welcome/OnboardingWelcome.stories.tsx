import { Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
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

export const NoProductSelected: Story = {
    render: () => {
        useDelayedOnMountEffect(() => {
            router.actions.push(urls.onboardingWelcome())
        })
        return <App />
    },
    parameters: {
        testOptions: { waitForSelector: '[data-attr="onboarding-project-token"]' },
    },
}

export const ProductSelected: Story = {
    render: () => {
        useDelayedOnMountEffect(() => {
            router.actions.push(urls.onboardingWelcome(), { product: ProductKey.SESSION_REPLAY })
        })
        return <App />
    },
    parameters: {
        testOptions: { waitForSelector: '[data-attr="sdk-continue"]' },
    },
}
