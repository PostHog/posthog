import { Meta, StoryObj } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { availableOnboardingProducts } from 'scenes/onboarding/shared/utils'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { onboardingLogic } from '../../../onboardingLogic'

/** The onboarding install step: the full layout and the simple flow's compact layout. */

const meta: Meta = {
    title: 'Scenes-Other/Onboarding/Install Step',
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
                '/api/billing/': { ...billingJson },
            },
            patch: {
                '/api/environments/:team_id/add_product_intent/': {},
            },
        }),
    ],
}
export default meta

type Story = StoryObj

/** Lands on the install step for product analytics. */
function installStepStory({
    featureFlags = {},
    simple = false,
}: {
    featureFlags?: Record<string, string | boolean>
    simple?: boolean
}): Story {
    return {
        render: () => {
            useMountedLogic(onboardingLogic)
            const { setProduct } = useActions(onboardingLogic)

            useDelayedOnMountEffect(() => {
                if (simple) {
                    router.actions.push(urls.simpleOnboarding(), {
                        step: `${OnboardingStepKey.INSTALL}:${ProductKey.PRODUCT_ANALYTICS}`,
                    })
                    return
                }
                setProduct(availableOnboardingProducts[ProductKey.PRODUCT_ANALYTICS])
                router.actions.push(
                    urls.onboarding({ productKey: ProductKey.PRODUCT_ANALYTICS, stepKey: OnboardingStepKey.INSTALL })
                )
            })

            return <App />
        },
        parameters: { featureFlags, testOptions: { waitForSelector: '[data-attr="wizard-command-block"]' } },
    }
}

/** The intro, the CLI command block, and the framework badges. */
export const ControlArm: Story = installStepStory({})

/** The simple flow's compact install step. */
export const SimpleFlow: Story = installStepStory({
    simple: true,
    featureFlags: { [FEATURE_FLAGS.ONBOARDING_SIMPLE_FLOW]: 'test' },
})
