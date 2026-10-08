import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { Decorator, Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import { billingUnsubscribedJson } from '~/mocks/fixtures/_billing_unsubscribed'
import { BillingType } from '~/types'

// The scene fills the window and scrolls its content column, but the visual-regression runner
// lets a fullscreen scene grow to its full content height. The climbing hedgehog sizes itself
// against the height of its column, so without a window-sized box it has nothing to measure.
const withPinnedSceneHeight: Decorator = function PinnedSceneHeightDecorator(Story): JSX.Element {
    return (
        <>
            <style>{'.Navigation3000 { height: 720px !important; min-height: 0 !important; }'}</style>
            <Story />
        </>
    )
}

function withBilling(billing: BillingType): Decorator {
    return mswDecorator({ get: { '/api/billing/': billing } })
}

/** Signs the story in as someone whose email domain the program does not accept. */
const withPersonalEmailDomain: Decorator = mswDecorator({
    get: {
        '/api/users/@me/': {
            ...MOCK_DEFAULT_USER,
            email: 'jane@gmail.com',
            organization: MOCK_DEFAULT_ORGANIZATION,
            pending_invites: [],
        },
    },
})

function renderStartupProgram(referrer?: string): () => JSX.Element {
    return function StartupProgramStory(): JSX.Element {
        useDelayedOnMountEffect(() => router.actions.push(urls.startups(referrer)))
        return <App />
    }
}

// One story per rendering of the page: what step 1 shows depends on the subscription, and the YC
// referrer replaces the header, the benefit list and the form fields.
const meta: Meta = {
    title: 'Scenes-Other/Startup program',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-03-10',
        testOptions: {
            waitForSelector: '[data-attr="startup-program-submit"]',
            viewport: { width: 1440, height: 720 },
        },
    },
    decorators: [withPinnedSceneHeight],
}
export default meta

type Story = StoryObj<{}>

// No subscription yet, so step 1 asks for billing details before the application counts.
export const NeedsBillingDetails: Story = {
    decorators: [withBilling(billingUnsubscribedJson)],
    render: renderStartupProgram(),
}

export const OnPaidPlan: Story = {
    decorators: [withBilling(billingJson)],
    render: renderStartupProgram(),
}

// The `yc` referrer is the Y Combinator offer: annual credits, the YC verification fields, and
// the footnotes under the benefit list.
export const YCOffer: Story = {
    decorators: [withBilling(billingJson)],
    render: renderStartupProgram('yc'),
}

// A personal email domain replaces the form with the gate that sends the applicant to settings.
export const EmailDomainBlocked: Story = {
    parameters: { testOptions: { waitForSelector: '[data-slot="empty-title"]' } },
    decorators: [withPersonalEmailDomain, withBilling(billingJson)],
    render: renderStartupProgram(),
}
