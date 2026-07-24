import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import {
    CacheBuster,
    installationStateDecorator,
    richScenarioDecorators,
    scenarioMocks,
} from './quickstartStoryScenarios'

// The test2 arm: focused install before the first event, then a computed hero answer above
// the product cards, and nothing below them. No publications rail means no external artwork,
// so unlike the full page these stories can run visual regression.
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

/** State C with rich data: hero answer (web analytics pageviews) above the cards */
export const Base: Story = {
    decorators: richScenarioDecorators,
}

/** State C, hero precedence 2: no pageviews, so the exceptions answer leads */
export const HeroErrorTracking: Story = {
    decorators: [
        mswDecorator(
            scenarioMocks(
                { totalEvents: 9000, backendEvents: 9000, exceptions: 42, serverExceptions: 3 },
                { symbolSets: 1 }
            )
        ),
    ],
}

/** State C, hero fallback: events flowing but nothing distinctive — generic explore answer */
export const HeroEventsOnly: Story = {
    decorators: [mswDecorator(scenarioMocks({ totalEvents: 350, backendEvents: 350 }))],
}

/** State A: pre-ingestion, the page collapses to the focused install view — wizard CTA + per-tool setup, no cards */
export const FocusedInstall: Story = {
    decorators: [installationStateDecorator('not_started'), mswDecorator(scenarioMocks({}, {}, 'not_started'))],
}

/** State B: a wizard run is active pre-ingestion, so its progress is the page hero */
export const WizardRunning: Story = {
    decorators: [installationStateDecorator('running'), mswDecorator(scenarioMocks({}, {}, 'running'))],
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
    play: async () => {
        await waitFor(
            () => {
                const installationProgress = document.querySelector('[data-attr="quickstart-installation-progress"]')
                if (!installationProgress?.textContent?.includes('Installing the PostHog SDK')) {
                    throw new Error('Quickstart installation task is not ready')
                }
            },
            { timeout: 8000, interval: 200 }
        )
    },
}
