import { Meta, StoryObj } from '@storybook/react'

import { InstallationProgress, InstallationStepStatus } from './installationProgressLogic'
import { InstallationProgressContent } from './InstallationProgressView'

/**
 * Every state of the Installation layer's progress view, driven by fixtures (the component is pure, so
 * no streams/mocks). Covers the happy path and each failure point so the error UI is reviewable at a
 * glance.
 */
const meta: Meta<typeof InstallationProgressContent> = {
    title: 'Scenes-Other/Onboarding/Shared/Installation Progress',
    component: InstallationProgressContent,
    // Provide the local-fallback callback to every story so the failed-run states show the full
    // "Run it yourself" + "Read the docs" recovery (no-op on non-error phases).
    argTypes: { onRetryLocally: { action: 'retry-locally' } },
    // Most stories here render an in-progress spinner by design (connecting/running phases), which never
    // resolves — skip the test runner's default "wait for loaders to hide" check.
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
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
    args: { progress: progress({ phase: 'connecting' }), mode: 'cloud' },
}

export const ConnectingLocal: Story = {
    args: { progress: progress({ phase: 'connecting' }), mode: 'local' },
}

export const RunningProvisioning: Story = {
    args: { progress: progress({ steps: steps(['in_progress', 'pending', 'pending', 'pending']) }) },
}

// The wizard's own sub-steps (session tasks) replace the pipeline's aggregate wizard stage in the
// flat timeline, indistinguishable from pipeline steps.
const wizardSubSteps: InstallationProgress['steps'] = [
    { id: 'wizard-task:a', label: 'Detected Next.js', status: 'completed', detail: null, source: 'wizard' },
    { id: 'wizard-task:b', label: 'Installing the PostHog SDK', status: 'in_progress', detail: null, source: 'wizard' },
    { id: 'wizard-task:c', label: 'Wiring up event capture', status: 'pending', detail: null, source: 'wizard' },
]

export const RunningWizard: Story = {
    args: {
        progress: progress({
            steps: (() => {
                const stages = steps(['completed', 'completed', 'in_progress', 'pending'])
                return [...stages.slice(0, 2), ...wizardSubSteps, ...stages.slice(3)]
            })(),
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
        mode: 'cloud',
        dashboard: { id: 1, name: 'My app analytics' },
    },
}

// The local run's final handoff: the wizard finished on the user's machine, so the review + deploy
// steps are theirs — plus the dashboard the wizard built as the payoff CTA.
export const CompletedLocalHandoff: Story = {
    args: {
        progress: progress({
            phase: 'completed',
            steps: [
                { id: 'a', label: 'Detected Next.js', status: 'completed', detail: null },
                { id: 'b', label: 'Installed the PostHog SDK', status: 'completed', detail: null },
                { id: 'c', label: 'Wired up event capture', status: 'completed', detail: null },
                { id: 'd', label: 'Created a dashboard', status: 'completed', detail: null },
            ],
        }),
        mode: 'local',
        dashboard: { id: 1, name: 'My app analytics' },
    },
    argTypes: { onDismiss: { action: 'dismissed' } },
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
            error: { title: 'Installation failed', detail: 'Could not provision a sandbox, capacity limit reached.' },
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

// The floating FAB variant, terminal, so the dismiss affordance shows.
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

// Every state in one canvas for review (GROW-98). Reuses the individual stories' fixtures so each one
// keeps a single source of truth.
export const AllStates: Story = {
    parameters: { controls: { disable: true } },
    render: () => {
        const states: { label: string; args: Story['args'] }[] = [
            { label: 'Connecting (cloud)', args: Connecting.args },
            { label: 'Connecting (local)', args: ConnectingLocal.args },
            { label: 'Running: provisioning', args: RunningProvisioning.args },
            { label: 'Running: wizard', args: RunningWizard.args },
            { label: 'Pull request ready', args: PullRequestReady.args },
            { label: 'Completed', args: Completed.args },
            { label: 'Completed: local handoff', args: CompletedLocalHandoff.args },
            { label: 'Failed: provisioning', args: FailedProvisioning.args },
            { label: 'Failed: wizard', args: FailedWizard.args },
            { label: 'Failed: no detail', args: FailedNoDetail.args },
        ]
        return (
            <div className="flex flex-col gap-5">
                {states.map(({ label, args }) => (
                    <div key={label} className="flex flex-col gap-1">
                        <span className="text-xs font-medium text-muted">{label}</span>
                        <InstallationProgressContent
                            progress={args!.progress!}
                            mode={args!.mode}
                            dashboard={args!.dashboard}
                            onRetryLocally={() => {}}
                        />
                    </div>
                ))}
            </div>
        )
    },
}

// Configure the progress view live from the controls panel (GROW-98).
interface PlaygroundArgs {
    phase: InstallationProgress['phase']
    completedSteps: number
    currentTask: string
    prReady: boolean
}

export const Playground: StoryObj<PlaygroundArgs> = {
    argTypes: {
        phase: { control: 'select', options: ['connecting', 'running', 'completed', 'error'] },
        completedSteps: { control: { type: 'range', min: 0, max: 4 } },
        currentTask: { control: 'text' },
        prReady: { control: 'boolean' },
    },
    args: { phase: 'running', completedSteps: 2, currentTask: 'Detecting Next.js', prReady: false },
    render: (args) => {
        const statuses: InstallationStepStatus[] = [0, 1, 2, 3].map((i) =>
            i < args.completedSteps ? 'completed' : i === args.completedSteps ? 'in_progress' : 'pending'
        )
        const built = progress({
            phase: args.phase,
            steps: steps(statuses, args.currentTask ? { at: args.completedSteps, text: args.currentTask } : undefined),
            prUrl: args.prReady || args.phase === 'completed' ? 'https://github.com/acme-co/web/pull/42' : null,
            error:
                args.phase === 'error' ? { title: 'Installation failed', detail: 'Something stopped the run.' } : null,
        })
        return <InstallationProgressContent progress={built} onRetryLocally={() => {}} />
    },
}
