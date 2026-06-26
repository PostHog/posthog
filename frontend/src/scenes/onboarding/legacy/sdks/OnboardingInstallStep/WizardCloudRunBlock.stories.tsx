import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
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
import { IntegrationType, OnboardingStepKey } from '~/types'

import { onboardingLogic } from '../../onboardingLogic'
import { wizardCloudRunLogic } from './wizardCloudRunLogic'

/**
 * Stories for the "open a PR for me" cloud-run option on the onboarding install
 * step. Rendered through the full `<App />` scene (not the block in isolation),
 * because wizardCloudRunLogic connects to onboardingLogic — the install step is
 * its natural habitat, and this is how Onboarding.stories drives the same step.
 *
 * The block only appears when ONBOARDING_WIZARD_CLOUD_RUN='test' (set via the
 * featureFlags parameter — never imperatively, which the visual-regression
 * runtime drops) and preflight reports cloud/dev (so `isCloudOrDev` is true).
 */

const githubIntegration: IntegrationType = {
    id: 1,
    kind: 'github',
    display_name: 'acme-co',
    icon_url: '/static/services/github.png',
    config: { account: { name: 'acme-co', type: 'Organization' }, repository_selection: 'all' },
    created_at: '2024-01-01T00:00:00Z',
}

const githubReposResponse = {
    repositories: [
        { id: 1, name: 'web', full_name: 'acme-co/web' },
        { id: 2, name: 'api', full_name: 'acme-co/api' },
        { id: 3, name: 'mobile-app', full_name: 'acme-co/mobile-app' },
    ],
    has_more: false,
}

const meta: Meta = {
    title: 'Scenes-Other/Onboarding/Wizard Cloud Run',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
        featureFlags: { [FEATURE_FLAGS.ONBOARDING_WIZARD_CLOUD_RUN]: 'test' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud' },
                '/stats': {},
                '/events': {},
                '/api/billing/': { ...billingJson },
                '/api/environments/:team_id/integrations/:id/github_repos': githubReposResponse,
            },
            post: {
                // Scaffold endpoint — accepting the kickoff lets the live (non-snapshot)
                // story walk all the way to the queued state by clicking the button.
                '/api/projects/:team_id/wizard/cloud_runs': () => [201, { id: 'cloud-run-1' }],
            },
            patch: {
                '/api/environments/:team_id/add_product_intent/': {},
            },
        }),
    ],
}
export default meta

type Story = StoryObj

const PRODUCT = ProductKey.PRODUCT_ANALYTICS

/**
 * Lands on the PRODUCT_ANALYTICS install step with a given set of integrations,
 * optionally driving wizardCloudRunLogic into a later state. The logic is mounted
 * up front so `drive` can dispatch before the install-step block renders.
 */
function installStepStory({
    integrations,
    drive,
    waitForSelector,
    play,
}: {
    integrations: IntegrationType[]
    drive?: () => void
    waitForSelector: string
    play?: () => Promise<void>
}): Story {
    return {
        render: () => {
            useMountedLogic(onboardingLogic)
            useMountedLogic(wizardCloudRunLogic)
            const { setProduct } = useActions(onboardingLogic)

            useStorybookMocks({
                get: {
                    '/api/environments/:team_id/integrations': { results: integrations },
                },
            })

            useDelayedOnMountEffect(() => {
                setProduct(availableOnboardingProducts[PRODUCT])
                router.actions.push(urls.onboarding({ productKey: PRODUCT, stepKey: OnboardingStepKey.INSTALL }))
                drive?.()
            })

            return <App />
        },
        parameters: { testOptions: { waitForSelector } },
        play,
    }
}

/** No GitHub integration yet — the block offers a "Connect GitHub" button. */
export const NotConnected: Story = installStepStory({
    integrations: [],
    waitForSelector: '[data-attr="wizard-cloud-run-connect-github"]',
})

/** GitHub connected, no repo chosen — repo picker shown, "Open my pull request" disabled. */
export const Connected: Story = installStepStory({
    integrations: [githubIntegration],
    waitForSelector: '[data-attr="wizard-cloud-run-open-pr"]',
})

/** Repo selected — the primary button is enabled and ready to fire. The picker's
 * option keys are repo names, so we select by name ('web' → labelled 'acme-co/web'). */
export const RepoSelected: Story = installStepStory({
    integrations: [githubIntegration],
    drive: () => wizardCloudRunLogic.actions.setSelectedRepository('web'),
    waitForSelector: '[data-attr="wizard-cloud-run-open-pr"]',
})

/** Run kicked off — non-blocking confirmation; Continue unblocks and the FAB takes over. */
export const PullRequestQueued: Story = installStepStory({
    integrations: [githubIntegration],
    drive: () => {
        wizardCloudRunLogic.actions.setSelectedRepository('web')
        wizardCloudRunLogic.actions.startCloudRunSuccess()
    },
    waitForSelector: '[data-attr="wizard-cloud-run-queued"]',
})

/** The other half of the same wizard — toggling to "Run it yourself" reveals the CLI command. */
export const RunItYourself: Story = installStepStory({
    integrations: [],
    waitForSelector: '[data-attr="wizard-command-block"]',
    play: async () => {
        await waitFor(() => {
            if (!document.querySelector('[data-attr="wizard-install-mode-local"]')) {
                throw new Error('install-mode toggle not ready')
            }
        })
        await userEvent.click(document.querySelector('[data-attr="wizard-install-mode-local"]') as Element)
    },
})
