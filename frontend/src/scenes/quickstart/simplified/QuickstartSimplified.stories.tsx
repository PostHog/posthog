import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import {
    CacheBuster,
    installDismissedDecorator,
    installationStateDecorator,
    richScenarioDecorators,
    scenarioMocks,
} from '../quickstartStoryScenarios'

// The test2 arm: focused install before the first event, then the tool grids and nothing
// else. No publications rail means no external artwork, so unlike the full page these
// stories can run visual regression.
const meta: Meta = {
    component: App,
    title: 'Scenes-App/Quickstart/Simplified (test2)',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-07-15',
        pageUrl: urls.quickstart(),
        featureFlags: {
            [FEATURE_FLAGS.QUICKSTART_HOMEPAGE]: 'test2',
            [FEATURE_FLAGS.ONBOARDING_WIZARD_SYNC]: 'test',
            [FEATURE_FLAGS.ONBOARDING_WIZARD_CLOUD_RUN]: 'test',
        },
    },
    decorators: [CacheBuster],
}
export default meta

type Story = StoryObj<{}>

/** State C with rich data: live stats on the featured cards, plain rows below */
export const Base: Story = {
    decorators: richScenarioDecorators,
}

/** State C with little data: events flowing but most tools still waiting */
export const EventsOnly: Story = {
    decorators: [mswDecorator(scenarioMocks({ totalEvents: 350, backendEvents: 350 }))],
}

/** State A: pre-ingestion, the page collapses to the focused install view — wizard CTA + per-tool setup, no cards */
export const FocusedInstall: Story = {
    decorators: [installationStateDecorator('not_started'), mswDecorator(scenarioMocks({}, {}, 'not_started'))],
}

/** Pre-ingestion but dismissed: the normal page with a waiting banner linking back to setup */
export const InstallDismissedBanner: Story = {
    decorators: [
        installDismissedDecorator,
        installationStateDecorator('not_started'),
        mswDecorator(scenarioMocks({}, {}, 'not_started')),
    ],
}

/** Dismissed while a run is active: the header shows a simple loading chip back into setup */
export const InstallDismissedWizardRunning: Story = {
    decorators: [
        installDismissedDecorator,
        installationStateDecorator('running'),
        mswDecorator(scenarioMocks({}, {}, 'running')),
    ],
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}

/** State B: a wizard run is active pre-ingestion, so its progress is the page hero */
export const WizardRunning: Story = {
    decorators: [installationStateDecorator('running'), mswDecorator(scenarioMocks({}, {}, 'running'))],
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
    play: async () => {
        await waitFor(
            () => {
                const installationProgress = document.querySelector('[data-attr="quickstart-run-status"]')
                if (!installationProgress?.textContent?.includes('Installing the PostHog SDK')) {
                    throw new Error('Quickstart installation task is not ready')
                }
            },
            { timeout: 8000, interval: 200 }
        )
    },
}
