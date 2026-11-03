import { MOCK_TEAM_ID } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
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
import { IntegrationType, OnboardingStepKey } from '~/types'

import { onboardingLogic } from '../../../onboardingLogic'
import { activeCloudRunLogic } from '../../../shared/wizard-sync/activeCloudRunLogic'

/**
 * The onboarding install step under each arm of the cloud-wizard AB test (GROW-117), plus the
 * pinned progress state once a cloud run is underway. The cloud run block's own states live in the
 * Wizard Cloud Run stories.
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
        {
            id: 1,
            name: 'web',
            full_name: 'acme-co/web',
            private: false,
            default_branch: 'main',
            language: 'TypeScript',
            pushed_at: '2023-05-24T10:00:00Z',
            archived: false,
            can_push: true,
        },
    ],
    has_more: false,
}

// One SSE frame. The task-run stream speaks `data:`-only messages (default event type), so the
// EventSource `onmessage` handler picks them up.
const sseEvent = (data: object): string => `data: ${JSON.stringify(data)}\n\n`
const sseStep = (group: string, step: string, status: string, label: string, detail: string | null = null): string =>
    sseEvent({
        type: 'notification',
        notification: { method: '_posthog/progress', params: { group, step, status, label, detail } },
    })

// A mid-run pipeline snapshot, replayed to the InstallationProgressView the moment it connects. The
// trailing `stream-end` sentinel makes the logic close the EventSource, so the rendered state is
// stable for the snapshot (no reconnect churn).
const TASK_RUN_STREAM_BODY = [
    sseEvent({
        type: 'task_run_state',
        status: 'in_progress',
        stage: 'work',
        output: null,
        branch: null,
        error_message: null,
        updated_at: '2023-05-25T00:00:00Z',
        completed_at: null,
    }),
    sseStep('setup', 'sandbox', 'completed', 'Set up sandbox'),
    sseStep('setup', 'clone', 'completed', 'Cloned repository'),
    sseStep('setup', 'wizard', 'in_progress', 'Running setup wizard', 'Detecting Next.js'),
    sseStep('deliver', 'pr', 'pending', 'Opening pull request'),
    'event: stream-end\ndata: {}\n\n',
].join('')

const meta: Meta = {
    title: 'Scenes-Other/Onboarding/Install Step',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
        // The cloud tab and the pinned run render spinners by design (repo loading, in-progress
        // steps) — skip the test runner's default "wait for loaders to hide" check.
        testOptions: { waitForLoadersToDisappear: false },
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud' },
                '/stats': {},
                '/events': {},
                '/api/billing/': { ...billingJson },
                '/api/projects/:team_id/integrations': { results: [githubIntegration] },
                '/api/environments/:team_id/integrations/:id/github_repos': githubReposResponse,
                '/api/projects/:project_id/tasks/:task_id/runs/:run_id/stream': () =>
                    new Response(TASK_RUN_STREAM_BODY, {
                        status: 200,
                        headers: { 'Content-Type': 'text/event-stream' },
                    }),
                // No wizard session enriching the run in these stories; a 404 closes the EventSource
                // without retries (the pipeline above is the only progress source).
                '/api/projects/:project_id/wizard/sessions/stream': () => [404],
            },
            patch: {
                '/api/environments/:team_id/add_product_intent/': {},
            },
        }),
    ],
}
export default meta

type Story = StoryObj

/** Lands on the install step for product analytics, optionally staging extra state first. */
function installStepStory({
    featureFlags = {},
    drive,
    waitForSelector,
    play,
    simple = false,
}: {
    featureFlags?: Record<string, string | boolean>
    drive?: () => void
    waitForSelector: string
    play?: () => Promise<void>
    simple?: boolean
}): Story {
    return {
        render: () => {
            useMountedLogic(onboardingLogic)
            useMountedLogic(activeCloudRunLogic)
            const { setProduct } = useActions(onboardingLogic)

            useDelayedOnMountEffect(() => {
                // activeCloudRun is persisted (survives a refresh mid-run) — clear any handle left
                // over from an earlier story in the same browser session before driving this one.
                activeCloudRunLogic.actions.clearActiveCloudRun()
                drive?.()
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
        parameters: { featureFlags, testOptions: { waitForSelector } },
        play,
    }
}

/**
 * Control arm: no cloud option — the intro, the CLI command block, and the framework badges. The flag
 * is deliberately UNSET rather than 'control': storybook's useFeatureFlag treats any truthy value as
 * flag-on (the variant match is ignored there), and the control arm renders the flag-off branch anyway.
 */
export const ControlArm: Story = installStepStory({
    waitForSelector: '[data-attr="wizard-command-block"]',
})

/** Test arm: the cloud/local toggle with the "open a PR" block up front (GitHub connected). */
export const TestArm: Story = installStepStory({
    featureFlags: { [FEATURE_FLAGS.ONBOARDING_WIZARD_CLOUD_RUN]: 'test' },
    waitForSelector: '[data-attr="wizard-cloud-run-open-pr"]',
})

const startCloudRun = (): void =>
    activeCloudRunLogic.actions.setActiveCloudRun('task-1', 'run-1', new Date().toISOString(), MOCK_TEAM_ID)

// The panel mounts in the 'connecting' phase; hold the snapshot until the mocked stream's pipeline
// steps have rendered so it captures the mid-run timeline, not the placeholder.
const waitForPipelineTimeline = async (): Promise<void> => {
    await waitFor(
        () => {
            const timeline = document.querySelector('[data-attr="installation-progress"]')
            if (!timeline?.textContent?.includes('Running setup wizard')) {
                throw new Error('pipeline timeline not ready')
            }
        },
        { timeout: 8000, interval: 200 }
    )
}

/**
 * A cloud run underway: the step pins to the run's live pipeline (fed by the mocked task-run
 * stream), the local tab is blocked, and Continue is unblocked.
 */
export const CloudRunInProgress: Story = installStepStory({
    featureFlags: { [FEATURE_FLAGS.ONBOARDING_WIZARD_CLOUD_RUN]: 'test' },
    drive: startCloudRun,
    waitForSelector: '[data-attr="installation-progress"]',
    play: waitForPipelineTimeline,
})

const SIMPLE_FLOW_CLOUD_FLAGS = {
    [FEATURE_FLAGS.ONBOARDING_SIMPLE_FLOW]: 'test',
    [FEATURE_FLAGS.ONBOARDING_WIZARD_CLOUD_RUN]: 'test',
}

/** The simple flow's compact install step on the cloud arm, with GitHub connected. */
export const SimpleFlowCloudArm: Story = installStepStory({
    simple: true,
    featureFlags: SIMPLE_FLOW_CLOUD_FLAGS,
    waitForSelector: '[data-attr="wizard-cloud-run-open-pr"]',
})

/** A cloud run underway in the simple flow: the compact step pins to the run's live pipeline. */
export const SimpleFlowCloudRunInProgress: Story = installStepStory({
    simple: true,
    featureFlags: SIMPLE_FLOW_CLOUD_FLAGS,
    drive: startCloudRun,
    waitForSelector: '[data-attr="installation-progress"]',
    play: waitForPipelineTimeline,
})
