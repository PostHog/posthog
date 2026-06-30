import { Meta, StoryObj } from '@storybook/react'

import { InstallationProgress, InstallationStepStatus } from './installationProgressLogic'
import { InstallationProgressContent } from './InstallationProgressView'

/**
 * Every state of the Installation layer's progress view, driven by fixtures (the component is pure, so
 * no streams/mocks). Covers the happy path and each failure point so the error UI is reviewable at a
 * glance.
 */
const meta: Meta<typeof InstallationProgressContent> = {
    title: 'Scenes-Other/Onboarding/Installation Progress',
    component: InstallationProgressContent,
    // Width-bound to the onboarding card so the stepper wraps as it does in product.
    decorators: [
        (Story) => (
            <div className="max-w-xl">
                <Story />
            </div>
        ),
    ],
}
export default meta
type Story = StoryObj<typeof InstallationProgressContent>

const STAGES = ['Provisioning sandbox', 'Cloning repository', 'Running setup wizard', 'Opening pull request']

// Pipeline steps with a status per stage (index-aligned to STAGES), with optional detail on one stage.
function steps(
    statuses: InstallationStepStatus[],
    detail?: { at: number; text: string }
): InstallationProgress['steps'] {
    return STAGES.map((label, i) => ({
        id: `setup:${i}`,
        label,
        status: statuses[i] ?? 'pending',
        detail: detail && detail.at === i ? detail.text : null,
    }))
}

function progress(overrides: Partial<InstallationProgress>): InstallationProgress {
    return { phase: 'running', steps: [], error: null, prUrl: null, isCurrent: true, ...overrides }
}

export const Connecting: Story = {
    args: { progress: progress({ phase: 'connecting' }) },
}

export const RunningProvisioning: Story = {
    args: { progress: progress({ steps: steps(['in_progress', 'pending', 'pending', 'pending']) }) },
}

export const RunningWizard: Story = {
    args: {
        progress: progress({
            steps: steps(['completed', 'completed', 'in_progress', 'pending'], { at: 2, text: 'Detecting Next.js' }),
        }),
    },
}

export const Completed: Story = {
    args: {
        progress: progress({
            phase: 'completed',
            steps: steps(['completed', 'completed', 'completed', 'completed']),
            prUrl: 'https://github.com/acme-co/web/pull/42',
        }),
    },
}

// The PR is open but the run keeps going (keeping CI green): "Pull request ready" headline + the review
// CTA surface mid-run, and the keep-green step shows as active rather than the run looking stuck.
export const PullRequestReady: Story = {
    args: {
        progress: progress({
            phase: 'running',
            prUrl: 'https://github.com/acme-co/web/pull/42',
            steps: [
                { id: 'setup:sandbox', label: 'Set up sandbox', status: 'completed', detail: null },
                { id: 'setup:clone', label: 'Cloned repository', status: 'completed', detail: null },
                { id: 'setup:wizard', label: 'Ran PostHog setup wizard', status: 'completed', detail: null },
                { id: 'setup:agent', label: 'Started agent', status: 'completed', detail: null },
                { id: 'deliver:pr', label: 'Opened pull request', status: 'completed', detail: null },
                { id: 'deliver:ci', label: 'Keeping CI green', status: 'in_progress', detail: null },
            ],
        }),
    },
}

export const FailedProvisioning: Story = {
    args: {
        progress: progress({
            phase: 'error',
            steps: steps(['failed', 'pending', 'pending', 'pending']),
            error: { title: 'Installation failed', detail: 'Could not provision a sandbox — capacity limit reached.' },
        }),
    },
}

export const FailedClone: Story = {
    args: {
        progress: progress({
            phase: 'error',
            steps: steps(['completed', 'failed', 'pending', 'pending']),
            error: { title: 'Installation failed', detail: 'git clone failed: repository not found or no access.' },
        }),
    },
}

export const FailedWizard: Story = {
    args: {
        progress: progress({
            phase: 'error',
            steps: steps(['completed', 'completed', 'failed', 'pending']),
            error: { title: 'Installation failed', detail: 'PostHog setup wizard failed with exit code 1.' },
        }),
    },
}

export const FailedNoDetail: Story = {
    args: {
        progress: progress({
            phase: 'error',
            steps: steps(['completed', 'completed', 'completed', 'failed']),
            error: { title: 'Installation failed', detail: null },
        }),
    },
}

// The floating FAB variant — terminal, so the dismiss affordance shows.
export const FloatingDismissible: Story = {
    args: {
        progress: progress({
            phase: 'completed',
            steps: steps(['completed', 'completed', 'completed', 'completed']),
            prUrl: 'https://github.com/acme-co/web/pull/42',
        }),
    },
    argTypes: { onDismiss: { action: 'dismissed' } },
    decorators: [
        (Story) => (
            <div className="w-[340px]">
                <Story />
            </div>
        ),
    ],
}
