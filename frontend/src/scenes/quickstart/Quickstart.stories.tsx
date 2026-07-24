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

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Quickstart/Full page (test)',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-07-15',
        pageUrl: urls.quickstart(),
        // The scene only renders for the test variants of the experiment flag
        featureFlags: {
            [FEATURE_FLAGS.QUICKSTART_HOMEPAGE]: 'test',
            [FEATURE_FLAGS.ONBOARDING_WIZARD_SYNC]: 'test',
        },
    },
    // External artwork (Substack covers in the publications rail) makes pixel snapshots nondeterministic
    tags: ['test-skip'],
    decorators: [CacheBuster],
}
export default meta

type Story = StoryObj<{}>

/** A team mid-journey: several tools live, several waiting, quality partially climbed */
export const Base: Story = {
    decorators: richScenarioDecorators,
}

/** Nothing has sent data in the window: every event-based tool decays back to ready/needs setup */
export const QuietProject: Story = {
    decorators: [mswDecorator(scenarioMocks({}))],
}

/** Fresh account without a wizard run: the header links back to the onboarding installation step. */
export const InstallationNotStarted: Story = {
    decorators: [installationStateDecorator('not_started'), mswDecorator(scenarioMocks({}))],
}

/** Fresh account with a wizard run: a compact status chip gets its own row below the token and the global FAB stays hidden. */
export const InstallationRunning: Story = {
    decorators: [installationStateDecorator('running'), mswDecorator(scenarioMocks({}))],
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
    play: async () => {
        await waitFor(
            () => {
                const installationProgress = document.querySelector('[data-attr="quickstart-installation-progress"]')
                const productAnalyticsProgress = document.querySelector('[data-attr="quickstart-product-installing"]')
                if (!installationProgress?.textContent?.includes('Installing the PostHog SDK')) {
                    throw new Error('Quickstart installation task is not ready')
                }
                if (!productAnalyticsProgress?.textContent?.includes('Installing the PostHog SDK')) {
                    throw new Error('Product analytics installation state is not ready')
                }
            },
            { timeout: 8000, interval: 200 }
        )
    },
}

/** Installed project without a wizard run: no installation CTA is shown in the header. */
export const InstallationComplete: Story = {
    decorators: [installationStateDecorator('complete'), mswDecorator(scenarioMocks({ totalEvents: 120 }))],
}

/** Everything wired: all tools live with deep quality — the "topped out" look */
export const EverythingLive: Story = {
    decorators: [
        mswDecorator(
            scenarioMocks(
                {
                    totalEvents: 812000,
                    prodEvents: 640000,
                    customEvents: 90000,
                    distinctCustomEvents: 42,
                    identifyCalls: 51000,
                    exceptions: 3100,
                    serverExceptions: 1200,
                    backendEvents: 210000,
                    flagCalls: 88000,
                    prodFlagCalls: 61000,
                    pageviews: 402000,
                    prodPageviews: 350000,
                    surveyResponses: 640,
                    aiGenerations: 12000,
                    aiTraceEvents: 4000,
                    mcpInitialize: 90,
                    mcpToolCalls: 4200,
                },
                {
                    hasLogs: true,
                    sources: 3,
                    workflows: 4,
                    eventTriggeredWorkflows: 2,
                    symbolSets: 5,
                    errorAlerts: 2,
                    tickets: 230,
                }
            )
        ),
    ],
}
