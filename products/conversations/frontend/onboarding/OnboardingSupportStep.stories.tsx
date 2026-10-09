import { Meta, StoryObj } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { router } from 'kea-router'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { onboardingLogic } from 'scenes/onboarding/legacy/onboardingLogic'
import { availableOnboardingProducts } from 'scenes/onboarding/shared/utils'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

const meta: Meta = {
    title: 'Scenes-Other/Onboarding/Legacy/Support setup',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
        testOptions: { waitForSelector: '[data-attr="onboarding-support-step"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud' },
            },
            patch: {
                '/api/environments/:team_id/add_product_intent/': {},
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const SupportSetup: Story = {
    render: () => {
        useMountedLogic(onboardingLogic)
        const { setProduct } = useActions(onboardingLogic)

        useDelayedOnMountEffect(() => {
            setProduct(availableOnboardingProducts[ProductKey.CONVERSATIONS])
            router.actions.push(
                urls.onboarding({
                    productKey: ProductKey.CONVERSATIONS,
                    stepKey: OnboardingStepKey.PRODUCT_CONFIGURATION,
                })
            )
        })

        return <App />
    },
}
