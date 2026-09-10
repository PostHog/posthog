import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { useMountedLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { useDelayedOnMountEffect, useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { IntegrationType } from '~/types'

import { activeCloudRunLogic } from './activeCloudRunLogic'
import { WizardCloudRunBlock } from './WizardCloudRunBlock'
import { wizardCloudRunLogic } from './wizardCloudRunLogic'
import { WizardCommandBlock } from './WizardCommandBlock'
import { WizardInstallOptions } from './WizardInstallOptions'

/**
 * Stories for the "open a PR for me" cloud-run option: the block's own states, rendered on their own
 * rather than through an onboarding scene.
 *
 * In the product the block sits on the legacy install step — the self-driving flow forces the cloud
 * arm off, because its run is interactive and the cloud runner is headless. `Legacy/Install Step`
 * already snapshots the block in that setting, so driving a scene from here would duplicate those
 * snapshots (and, if it drove the self-driving flow, snapshot a step where the block cannot appear).
 * These stories cover what no scene story does: not-connected, repo picking, queued, and the toggle
 * back to running it yourself.
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
    title: 'Scenes-Other/Onboarding/Shared/Wizard Cloud Run',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
        // Legacy flow, deliberately: the self-driving install step forces the cloud arm off (its run
        // is interactive and the cloud runner is headless), so the block only renders here.
        featureFlags: {
            [FEATURE_FLAGS.ONBOARDING_WIZARD_CLOUD_RUN]: 'test',
        },
        // The block is mid-flight by design in several of these (connecting/polling/queued) — skip the
        // test runner's default "wait for loaders to hide" check.
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

// The block seeds its state from a delayed-mount effect, and the repo picker's options arrive over a
// mocked request, so play-function waits need a load-tolerant budget: on a busy CI shard an
// under-budgeted wait fails all three retries instead of flaking once.
const WAIT_OPTIONS = { timeout: 30000, interval: 200 }

/**
 * The block on its own, with a given set of integrations and optionally driven into a later state.
 *
 * Deliberately not rendered through an onboarding scene. The block lives on the legacy install step
 * (the self-driving flow forces the cloud arm off — its run is interactive and the cloud runner is
 * headless), and `Legacy/Install Step` already snapshots it in place. Driving a scene from here
 * would duplicate those snapshots rather than capture what this file is about: the block's own
 * states, which no scene story covers.
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
                drive?.()
            })

            return (
                <div className="max-w-xl">
                    <WizardCloudRunBlock />
                </div>
            )
        },
        parameters: { testOptions: { waitForSelector } },
        play: extraPlay ? async () => await extraPlay() : undefined,
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
        // LemonInput puts data-attr on the <input> element itself, so match the input directly —
        // a descendant selector like `[data-attr=...] input` never matches anything.
        await waitFor(() => {
            if (!document.querySelector('input[data-attr="select-github-repository"]')) {
                throw new Error('repo picker not ready')
            }
        }, WAIT_OPTIONS)
        await userEvent.click(document.querySelector('input[data-attr="select-github-repository"]') as Element)
        // full_name only appears in the open dropdown (nothing is selected), so this confirms it's open.
        await waitFor(() => {
            if (!Array.from(document.querySelectorAll('span')).some((el) => el.textContent === 'acme-co/mobile-app')) {
                throw new Error('repo options not open')
            }
        }, WAIT_OPTIONS)
    },
})

/** Run kicked off — non-blocking confirmation; the FAB takes over from here. */
export const PullRequestQueued: Story = {
    render: () => {
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

/**
 * The other half of the same wizard — toggling to "Run it yourself" reveals the CLI command. The
 * toggle belongs to `WizardInstallOptions`, which hosts the block, so this one renders that instead.
 */
export const RunItYourself: Story = {
    render: () => {
        useMountedLogic(wizardCloudRunLogic)
        useMountedLogic(activeCloudRunLogic)

        useStorybookMocks({
            get: {
                '/api/environments/:team_id/integrations': { results: [] },
            },
        })

        useDelayedOnMountEffect(() => {
            activeCloudRunLogic.actions.clearActiveCloudRun()
        })

        return (
            <div className="max-w-xl">
                <WizardInstallOptions localBlock={<WizardCommandBlock />} />
            </div>
        )
    },
    parameters: { testOptions: { waitForSelector: '[data-attr="wizard-command-block"]' } },
    play: async () => {
        await waitFor(() => {
            if (!document.querySelector('[data-attr="wizard-mode-local"]')) {
                throw new Error('install-mode toggle not ready')
            }
        }, WAIT_OPTIONS)
        await userEvent.click(document.querySelector('[data-attr="wizard-mode-local"]') as Element)
    },
}

interface PlaygroundArgs {
    githubConnected: boolean
    repository: '' | 'web' | 'api' | 'mobile-app'
    pullRequestQueued: boolean
}

/**
 * Interactive harness for the whole cloud-run flow: the controls panel drives whether GitHub is
 * connected, which repo is picked, and whether the PR has been queued. Keyed on the args so flipping
 * a control remounts the block and re-derives state from scratch — the logic reducers (selected repo,
 * run status) don't reset on their own, and the connected/not state comes from a render-time mock.
 */
function CloudRunPlayground({ githubConnected, repository, pullRequestQueued }: PlaygroundArgs): JSX.Element {
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
        if (repository) {
            wizardCloudRunLogic.actions.setSelectedRepository(repository)
        }
        if (pullRequestQueued) {
            wizardCloudRunLogic.actions.startCloudRunSuccess()
        }
    })

    return (
        <div className="max-w-xl">
            <WizardCloudRunBlock />
        </div>
    )
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
}
