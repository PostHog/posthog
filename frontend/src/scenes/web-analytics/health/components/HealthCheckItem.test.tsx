import { cleanup, fireEvent, render, within } from '@testing-library/react'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { OnboardingStepKey } from '~/types'

import { HealthCheck, HealthCheckId } from '../healthCheckTypes'
import { webAnalyticsHealthLogic } from '../webAnalyticsHealthLogic'
import { HealthCheckItem } from './HealthCheckItem'

const failingPageviewCheck: HealthCheck = {
    id: HealthCheckId.PAGEVIEW_EVENTS,
    category: 'events',
    title: '$pageview',
    description: 'Complete the PostHog installation to start seeing events in your dashboard.',
    status: 'error',
    action: {
        label: 'Complete installation',
        to: urls.onboarding({ productKey: ProductKey.WEB_ANALYTICS, stepKey: OnboardingStepKey.INSTALL }),
    },
    urgent: true,
}

describe('HealthCheckItem', () => {
    beforeEach(() => {
        initKeaTests()
        webAnalyticsHealthLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    test('clicking the check description opens the in-app install step', () => {
        const { container } = render(<HealthCheckItem check={failingPageviewCheck} />)

        // A real anchor, so a modifier click opens the step in a new tab like the button does.
        const summaryLink = within(container).getByText(failingPageviewCheck.description).closest('a')
        expect(summaryLink?.getAttribute('href')).toContain('/onboarding/web_analytics')

        fireEvent.click(within(container).getByText(failingPageviewCheck.description))

        expect(router.values.location.pathname).toContain('/onboarding/web_analytics')
        expect(router.values.searchParams.step).toEqual(OnboardingStepKey.INSTALL)
    })

    test('a check without an action keeps its text inert', () => {
        const { container } = render(<HealthCheckItem check={{ ...failingPageviewCheck, action: undefined }} />)

        expect(within(container).queryByRole('button')).toBeNull()
    })
})
