import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { useMountedLogic } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { useDelayedOnMountEffect, useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { IntegrationType } from '~/types'

import { onboardingLogic } from '../../../legacy/onboardingLogic'
import { activeCloudRunLogic } from './activeCloudRunLogic'
import { WizardCloudRunBlock } from './WizardCloudRunBlock'
import { wizardCloudRunLogic } from './wizardCloudRunLogic'

/**
 * Stories for the "open a PR for me" cloud-run option on the context-first onboarding install step.
 * Rendered through the full `<App />` scene: the welcome step shows first, then a play function clicks
 * "Get started" to land on the install step where the cloud-run block lives (it connects to
 * onboardingLogic, so the scene is its natural habitat).
 *
 * The block only appears when ONBOARDING_WIZARD_CLOUD_RUN='test' (set via the featureFlags parameter)
 * and preflight reports cloud/dev (so `isCloudOrDev` is true).
 */

const githubIntegration: IntegrationType = {
    id: 1,
    kind: 'github',
    display_name: 'acme-co',
    icon_url: '/static/services/github.png',
    config: { account: { name: 'acme-co', type: 'Organization' }, repository_selection: 'all' },
    created_at: '2024-01-01T00:00:00Z',
}

// Metadata-rich repos so the picker's option rows (language, default branch, recency, private/archived,
// write access) are exercised. pushed_at values are relative to the story's mockDate (2023-05-25).
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
        {
            id: 2,
            name: 'api',
            full_name: 'acme-co/api',
            private: true,
            default_branch: 'master',
            language: 'Python',
            pushed_at: '2023-05-11T10:00:00Z',
            archived: false,
            can_push: true,
        },
        {
            id: 3,
            name: 'mobile-app',
            full_name: 'acme-co/mobile-app',
            private: true,
            default_branch: 'develop',
            language: 'Swift',
            pushed_at: '2023-02-01T10:00:00Z',
            archived: true,
            can_push: false,
        },
    ],
    has_more: false,
}

const meta: Meta = {
    title: 'Scenes-Other/Onboarding/Wizard Cloud Run',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
        featureFlags: {
            [FEATURE_FLAGS.ONBOARDING_WIZARD_CLOUD_RUN]: 'test',
            [FEATURE_FLAGS.ONBOARDING_FLOW_VARIANT]: 'self-driving',
        },
        // These stories render the full app shell around a wizard step that's mid-flight by design
        // (connecting/polling/queued) — skip the test runner's default "wait for loaders to hide" check.
        testOptions: { waitForLoadersToDisappear: false },
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
                // Accepting the kickoff lets the live (non-snapshot) story walk all the way to the
                // queued state by clicking the button.
                '/api/wizard/cloud_run': () => [201, { task_id: 'task-1', run_id: 'run-1', status: 'queued' }],
            },
            patch: {
                '/api/environments/:team_id/add_product_intent/': {},
            },
        }),
    ],
}
export default meta

type Story = StoryObj

// Click a footer/body button by its exact label, waiting for it to mount first.
async function clickButton(text: string): Promise<void> {
    await waitFor(() => {
        const btn = Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.trim() === text)
        if (!btn) {
            throw new Error(`button "${text}" not ready`)
        }
    })
    const btn = Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.trim() === text)
    await userEvent.click(btn as Element)
}

/**
 * Lands on the context-first install step with a given set of integrations, optionally driving
 * wizardCloudRunLogic into a later state. The logic is mounted up front so `drive` can dispatch
 * before the install-step block renders; the play then advances welcome → install.
 */
function cloudRunStory({
    integrations,
    drive,
    waitForSelector,
    extraPlay,
}: {
    integrations: IntegrationType[]
    drive?: () => void
    waitForSelector: string
    extraPlay?: () => Promise<void>
}): Story {
    return {
        render: () => {
            useMountedLogic(onboardingLogic)
            useMountedLogic(wizardCloudRunLogic)
            useMountedLogic(activeCloudRunLogic)

            useStorybookMocks({
                get: {
                    '/api/environments/:team_id/integrations': { results: integrations },
                },
            })

            useDelayedOnMountEffect(() => {
                // activeCloudRun is persisted (survives a refresh mid-run) — clear any handle left
                // over from an earlier story in the same browser session before driving this one.
                activeCloudRunLogic.actions.clearActiveCloudRun()
                router.actions.push(urls.onboarding())
                drive?.()
            })

            return <App />
        },
        parameters: { testOptions: { waitForSelector } },
        play: async () => {
            await clickButton('Get started')
            await extraPlay?.()
        },
    }
}

/** No GitHub integration yet — the block offers a "Connect GitHub" button. */
export const NotConnected: Story = cloudRunStory({
    integrations: [],
    waitForSelector: '[data-attr="wizard-cloud-run-connect-github"]',
})

/** GitHub connected, no repo chosen — repo picker shown, "Install PostHog here" disabled. */
export const Connected: Story = cloudRunStory({
    integrations: [githubIntegration],
    waitForSelector: '[data-attr="wizard-cloud-run-open-pr"]',
})

/** Repo selected — the primary button is enabled and ready to fire. The picker's
 * option keys are repo names, so we select by name ('web' → labelled 'acme-co/web'). */
export const RepoSelected: Story = cloudRunStory({
    integrations: [githubIntegration],
    drive: () => wizardCloudRunLogic.actions.setSelectedRepository('web'),
    waitForSelector: '[data-attr="wizard-cloud-run-open-pr"]',
})

/** Repo picker opened — shows the metadata-rich option rows: language, default branch, recency, a lock
 * for private repos, an "Archived" tag, and a "No write access" warning where we can't open PRs. */
export const RepoPickerOpen: Story = cloudRunStory({
    integrations: [githubIntegration],
    waitForSelector: '[data-attr="select-github-repository"]',
    extraPlay: async () => {
        await waitFor(() => {
            if (!document.querySelector('[data-attr="select-github-repository"] input')) {
                throw new Error('repo picker not ready')
            }
        })
        await userEvent.click(document.querySelector('[data-attr="select-github-repository"] input') as Element)
        // full_name only appears in the open dropdown (nothing is selected), so this confirms it's open.
        await waitFor(() => {
            if (!Array.from(document.querySelectorAll('span')).some((el) => el.textContent === 'acme-co/mobile-app')) {
                throw new Error('repo options not open')
            }
        })
    },
})

/**
 * Run kicked off — non-blocking confirmation; the FAB takes over from here. Renders the block directly
 * (not through the full click-through `<App />` flow the other stories use): the queued state only
 * needs cloudRunStatus/selectedRepository seeded before mount, and going through "Get started" plus the
 * install step's own async setup raced the delayed-mount effect that drives every other story here.
 */
export const PullRequestQueued: Story = {
    render: () => {
        useMountedLogic(onboardingLogic)
        useMountedLogic(wizardCloudRunLogic)
        useMountedLogic(activeCloudRunLogic)

        useStorybookMocks({
            get: {
                '/api/environments/:team_id/integrations': { results: [githubIntegration] },
            },
        })

        useOnMountEffect(() => {
            activeCloudRunLogic.actions.clearActiveCloudRun()
            wizardCloudRunLogic.actions.setSelectedRepository('web')
            wizardCloudRunLogic.actions.startCloudRunSuccess()
        })

        return (
            <div className="max-w-xl">
                <WizardCloudRunBlock />
            </div>
        )
    },
    parameters: { testOptions: { waitForSelector: '[data-attr="wizard-cloud-run-queued"]' } },
}

/** The other half of the same wizard — toggling to "Run it yourself" reveals the CLI command. */
export const RunItYourself: Story = cloudRunStory({
    integrations: [],
    waitForSelector: '[data-attr="wizard-command-block"]',
    extraPlay: async () => {
        await waitFor(() => {
            if (!document.querySelector('[data-attr="context-wizard-mode-local"]')) {
                throw new Error('install-mode toggle not ready')
            }
        })
        await userEvent.click(document.querySelector('[data-attr="context-wizard-mode-local"]') as Element)
    },
})

interface PlaygroundArgs {
    githubConnected: boolean
    repository: '' | 'web' | 'api' | 'mobile-app'
    pullRequestQueued: boolean
}

/**
 * Interactive harness for the whole cloud-run flow: the controls panel drives whether GitHub is
 * connected, which repo is picked, and whether the PR has been queued. Keyed on the args so flipping
 * a control remounts the scene and re-derives state from scratch — the logic reducers (selected repo,
 * run status) don't reset on their own, and the connected/not state comes from a render-time mock.
 */
function CloudRunPlayground({ githubConnected, repository, pullRequestQueued }: PlaygroundArgs): JSX.Element {
    useMountedLogic(onboardingLogic)
    useMountedLogic(wizardCloudRunLogic)
    useMountedLogic(activeCloudRunLogic)

    useStorybookMocks({
        get: {
            '/api/environments/:team_id/integrations': {
                results: githubConnected ? [githubIntegration] : [],
            },
        },
    })

    useDelayedOnMountEffect(() => {
        activeCloudRunLogic.actions.clearActiveCloudRun()
        router.actions.push(urls.onboarding())
        if (repository) {
            wizardCloudRunLogic.actions.setSelectedRepository(repository)
        }
        if (pullRequestQueued) {
            wizardCloudRunLogic.actions.startCloudRunSuccess()
        }
    })

    return <App />
}

/** Fully controllable: flip GitHub on/off, pick a repo, and queue the PR straight from the controls panel. */
export const Playground: StoryObj<PlaygroundArgs> = {
    args: { githubConnected: true, repository: 'web', pullRequestQueued: false },
    argTypes: {
        githubConnected: {
            control: 'boolean',
            description: 'Whether a GitHub integration exists — off shows the "Connect GitHub" button',
        },
        repository: {
            control: 'select',
            options: ['', 'web', 'api', 'mobile-app'],
            description: 'Repository to pre-select — empty leaves "Install PostHog here" disabled',
        },
        pullRequestQueued: {
            control: 'boolean',
            description: 'Whether the run has been kicked off — on shows the queued confirmation',
        },
    },
    render: (args) => <CloudRunPlayground key={JSON.stringify(args)} {...args} />,
    parameters: { testOptions: { waitForSelector: '[data-attr="wizard-cloud-run-open-pr"]' } },
    play: async () => {
        await clickButton('Get started')
    },
}
