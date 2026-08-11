import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { availableOnboardingProducts } from 'scenes/onboarding/shared/utils'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey, UserRole } from '~/types'

import { onboardingLogic } from '../onboardingLogic'

const meta: Meta = {
    title: 'Scenes-Other/Onboarding/Legacy/Weekly reports',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
        featureFlags: {
            [FEATURE_FLAGS.ONBOARDING_AI_REPORTS]: 'test',
            [FEATURE_FLAGS.SUBSCRIPTION_AI_PROMPT]: true,
        },
        testOptions: { waitForSelector: '[data-attr="onboarding-ai-report-subscribe"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    cloud: true,
                    realm: 'cloud',
                },
                '/api/billing/': {
                    ...billingJson,
                },
            },
            post: {
                '/api/projects/:team_id/subscriptions/': () => [201, { id: 123 }],
            },
            patch: {
                '/api/environments/:team_id/add_product_intent/': {},
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

function StepForRole({ role }: { role: UserRole | null }): JSX.Element {
    useMountedLogic(onboardingLogic)
    const { setProduct } = useActions(onboardingLogic)

    useStorybookMocks({
        get: {
            '/api/users/@me/': () => [200, { ...MOCK_DEFAULT_USER, role_at_organization: role }],
        },
    })

    useDelayedOnMountEffect(() => {
        setProduct(availableOnboardingProducts[ProductKey.PRODUCT_ANALYTICS])
        router.actions.push(
            urls.onboarding({
                productKey: ProductKey.PRODUCT_ANALYTICS,
                // Namespaced id so currentFlowStep resolves via exact match — the step is
                // appended by a flag-gated flow rebuild (same race as the billing step).
                step: `${OnboardingStepKey.AI_REPORTS}:${ProductKey.PRODUCT_ANALYTICS}`,
            })
        )
    })

    return <App />
}

// One story per report family, not per role: founder/engineering share a report, and the
// remaining roles differ only in card copy drawn from aiReportDefinitions.

export const EngineeringReport: Story = {
    render: () => <StepForRole role={UserRole.Engineering} />,
}

export const MarketingReport: Story = {
    render: () => <StepForRole role={UserRole.Marketing} />,
}

export const LeadershipReport: Story = {
    render: () => <StepForRole role={UserRole.Leadership} />,
}

export const GenericReportWithoutRole: Story = {
    render: () => <StepForRole role={null} />,
}
