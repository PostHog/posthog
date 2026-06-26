import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { useMountedLogic } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import { billingUnsubscribedJson } from '~/mocks/fixtures/_billing_unsubscribed'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { onboardingLogic } from './legacy/onboardingLogic'

/**
 * Stories for the context-first onboarding flow. The onboarding scene resolves the `legacy` variant
 * by default (Onboarding.tsx → onboardingVariantRegistry → LegacyOnboarding → ContextOnboarding), so
 * pushing `urls.onboarding()` with no productKey lands on this flow — the new flow ignores productKey.
 *
 * ContextOnboarding is a fixed linear step flow driven by local state (no URL step param), so a story
 * that needs a later step advances by clicking the footer primary button ("Get started", then
 * "Continue") inside a `play` function. The steps, in order, are: Welcome, Install PostHog, Turn on
 * your sources, Connect your data, Pick a plan, Invite your team.
 */

// The wizard source catalog backing the "Connect your data" step's picker. A flat secret-key field on
// Stripe keeps the inline wizard demonstrable without pulling in OAuth/integration calls.
const WIZARD_SOURCES = {
    Github: { name: 'Github', iconPath: '/static/services/github.png', fields: [], caption: '', featured: true },
    Hubspot: { name: 'Hubspot', iconPath: '/static/services/hubspot.png', fields: [], caption: '', featured: true },
    Postgres: { name: 'Postgres', iconPath: '/static/services/postgres.png', fields: [], caption: '', featured: true },
    Stripe: { name: 'Stripe', iconPath: '/static/services/stripe.png', fields: [], caption: '', featured: true },
    Ashby: { name: 'Ashby', iconPath: '/static/services/ashby.png', fields: [], caption: '', featured: false },
    Supabase: { name: 'Supabase', iconPath: '/static/services/supabase.png', fields: [], caption: '', featured: false },
    Shopify: { name: 'Shopify', iconPath: '/static/services/shopify.png', fields: [], caption: '', featured: false },
}

const meta: Meta = {
    title: 'Scenes-Other/Onboarding',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    cloud: true,
                    realm: 'cloud',
                },
                '/stats': {},
                '/events': {},
                // Default to a subscribed org so most steps render without billing-specific copy; the
                // Billing story overrides this with the unsubscribed fixture to show the plan picker.
                '/api/billing/': {
                    ...billingJson,
                },
                // Source catalog for the "Connect your data" step picker.
                '/api/environments/:team_id/external_data_sources/wizard': () => [200, WIZARD_SOURCES],
            },
            patch: {
                // Marking onboarding intent / completion is fire-and-forget here.
                '/api/environments/:team_id/add_product_intent/': {},
            },
        }),
    ],
}
export default meta

type Story = StoryObj

/** Render the onboarding scene through the full app, landing on the context-first flow's first step. */
function OnboardingScene(): JSX.Element {
    useMountedLogic(onboardingLogic)

    useDelayedOnMountEffect(() => {
        // No productKey: the context-first flow ignores it and always starts at the Welcome step.
        router.actions.push(urls.onboarding())
    })

    return <App />
}

// Footer primary button labels, in the order the flow surfaces them: the first step says "Get
// started", later steps say "Continue", the final step says "Finish".
const PRIMARY_LABELS = ['Get started', 'Continue', 'Finish']

function findFooterPrimary(): HTMLButtonElement | null {
    return (
        Array.from(document.querySelectorAll<HTMLButtonElement>('button')).find((button) =>
            PRIMARY_LABELS.some((label) => button.textContent?.trim() === label)
        ) ?? null
    )
}

// Click the footer primary button (Get started / Continue) `times` times to advance that many steps,
// waiting for the button between clicks so each step has mounted before the next click.
async function advanceSteps(times: number): Promise<void> {
    for (let i = 0; i < times; i++) {
        const button = await waitFor(() => {
            const found = findFooterPrimary()
            if (!found) {
                throw new Error('Footer primary button not rendered')
            }
            return found
        })
        await userEvent.click(button)
    }
}

async function waitForText(text: string): Promise<void> {
    await waitFor(() => {
        if (!document.body.textContent?.includes(text)) {
            throw new Error(`Expected text not found: ${text}`)
        }
    })
}

// Welcome — the default landing step (index 0): hero image, headline, and a "Get started" button.
export const Welcome: Story = {
    render: () => <OnboardingScene />,
    parameters: {
        testOptions: { waitForSelector: '.OnboardingDottedBg' },
    },
    play: async () => {
        await waitForText("Let's make your product self-driving")
    },
}

// Install — one step in, the install step shows the wizard command block. With the cloud-run flag off
// (default) there is no segmented control, just the centered command.
export const Install: Story = {
    render: () => <OnboardingScene />,
    parameters: {
        testOptions: { waitForSelector: '[data-attr="wizard-command-block"]' },
    },
    play: async () => {
        await advanceSteps(1)
        await waitFor(() => {
            if (!document.querySelector('[data-attr="wizard-command-block"]')) {
                throw new Error('Wizard command block not rendered')
            }
            if (document.querySelector('[data-attr="context-wizard-mode-cloud"]')) {
                throw new Error('Cloud-run segmented control should not render with the flag off')
            }
        })
    },
}

// InstallWithCloudRun — with ONBOARDING_WIZARD_CLOUD_RUN='test' on cloud/dev, the install step offers
// a segmented "Open a pull request" vs "Run it yourself" control. The featureFlags parameter writes the
// variant to the always-merged baseline (persisted_feature_flags), and in Storybook useFeatureFlag
// ignores the `match` arg and only checks the flag is present — so the flag-ON branch renders in the
// visual snapshot from the parameter alone (no imperative override, which wouldn't reach featureFlagLogic).
export const InstallWithCloudRun: Story = {
    render: () => <OnboardingScene />,
    parameters: {
        featureFlags: { [FEATURE_FLAGS.ONBOARDING_WIZARD_CLOUD_RUN]: 'test' },
        testOptions: { waitForSelector: '[data-attr="context-wizard-mode-cloud"]' },
    },
    play: async () => {
        await advanceSteps(1)
        await waitFor(() => {
            if (
                !document.querySelector('[data-attr="context-wizard-mode-cloud"]') ||
                !document.querySelector('[data-attr="context-wizard-mode-local"]')
            ) {
                throw new Error('Cloud-run segmented control not rendered')
            }
        })
    },
}

// Sources — two steps in, the "Turn on your sources" step shows the per-tool cards (with team-property
// toggles) and the web-analytics authorized-domains input.
export const Sources: Story = {
    render: () => <OnboardingScene />,
    play: async () => {
        await advanceSteps(2)
        // Tool names render in sentence case (toSentenceCase): "Product analytics", "Session replay".
        await waitForText('Product analytics')
        await waitForText('Session replay')
        await waitForText('Authorized domains')
    },
}

// ConnectData — three steps in, the "Connect your data" step shows the inline warehouse source picker.
export const ConnectData: Story = {
    render: () => <OnboardingScene />,
    play: async () => {
        await advanceSteps(3)
        await waitFor(() => {
            if (!document.querySelector('input[type="search"]')) {
                throw new Error('Source picker search input not rendered')
            }
        })
        await waitForText('Stripe')
    },
}

// Billing — four steps in, the "Pick a plan" step. The unsubscribed billing fixture surfaces the
// Free vs Pay-as-you-go choice ("Continue on free" / "Add payment method").
export const Billing: Story = {
    render: () => {
        // Override the subscribed default so ContextBillingStep renders the plan picker, not the
        // already-subscribed state.
        useStorybookMocks({
            get: {
                '/api/billing/': {
                    ...billingUnsubscribedJson,
                },
            },
        })
        return <OnboardingScene />
    },
    play: async () => {
        await advanceSteps(4)
        await waitForText('Continue on free')
        await waitForText('Add payment method')
    },
}

// Invite — five steps in, the final "Invite your team" step shows the inline bulk-invite UI. We stop
// here without clicking Finish, which would navigate out of onboarding.
export const Invite: Story = {
    render: () => <OnboardingScene />,
    play: async () => {
        await advanceSteps(5)
        await waitFor(() => {
            if (!document.querySelector('[data-attr="invite-email-input"]')) {
                throw new Error('Invite UI not rendered')
            }
        })
        await waitForText('Invite your team')
    },
}
