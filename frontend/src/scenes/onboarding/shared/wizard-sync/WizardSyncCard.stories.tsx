import { Meta, StoryObj } from '@storybook/react'

import { InstallationProgress, InstallationStepStatus } from './installationProgressLogic'
import { WizardSyncCard, WizardSyncMode } from './WizardSyncCard'

/**
 * The detached wizard sync widget (collapsed), driven by fixtures so every cloud and local state is
 * reviewable in isolation. The component is pure, so no streams or mocks are needed.
 */
const meta: Meta<typeof WizardSyncCard> = {
    title: 'Scenes-Other/Onboarding/Wizard Sync Card',
    component: WizardSyncCard,
    argTypes: {
        onExpand: { action: 'expand' },
        onDismiss: { action: 'dismiss' },
    },
    // Most stories here render an in-progress spinner by design (connecting/running phases), which never
    // resolves — skip the test runner's default "wait for loaders to hide" check.
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
    decorators: [
        (Story) => (
            <div className="bg-primary p-8 flex justify-end">
                <Story />
            </div>
        ),
    ],
}
export default meta
type Story = StoryObj<typeof WizardSyncCard>

// Cloud pipeline steps with a status per stage, plus an optional live detail on one stage.
function cloudSteps(
    statuses: InstallationStepStatus[],
    detail?: { at: number; text: string }
): InstallationProgress['steps'] {
    const labels = [
        'Set up sandbox',
        'Cloned repository',
        'Ran PostHog setup wizard',
        'Started agent',
        'Opened pull request',
        'Keeping CI green',
    ]
    return labels.map((label, i) => ({
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
    args: { mode: 'cloud', elapsedSeconds: 3, progress: progress({ phase: 'connecting' }) },
}

// Cloud, wizard phase: the wizard's live sub-task ("Capturing events") leads the card.
export const CloudWizardRunning: Story = {
    args: {
        mode: 'cloud',
        elapsedSeconds: 134,
        progress: progress({
            steps: cloudSteps(['completed', 'completed', 'in_progress', 'pending', 'pending', 'pending'], {
                at: 2,
                text: 'Capturing events',
            }),
        }),
    },
}

// Cloud, agent has opened the PR and is keeping CI green.
export const CloudKeepingCiGreen: Story = {
    args: {
        mode: 'cloud',
        elapsedSeconds: 921,
        progress: progress({
            prUrl: 'https://github.com/acme-co/web/pull/42',
            steps: cloudSteps(['completed', 'completed', 'completed', 'completed', 'completed', 'in_progress']),
        }),
    },
}

// Local run: the wizard's own tasks are the steps.
export const LocalRunning: Story = {
    args: {
        mode: 'local',
        elapsedSeconds: 47,
        progress: progress({
            steps: [
                { id: 'plan', label: 'Plan event tracking', status: 'completed', detail: null },
                { id: 'install', label: 'Install PostHog', status: 'in_progress', detail: null },
                { id: 'capture', label: 'Capture events', status: 'pending', detail: null },
                { id: 'verify', label: 'Verify it works', status: 'pending', detail: null },
            ],
        }),
    },
}

export const Completed: Story = {
    args: {
        mode: 'cloud',
        elapsedSeconds: 1820,
        progress: progress({
            phase: 'completed',
            prUrl: 'https://github.com/acme-co/web/pull/42',
            steps: cloudSteps(['completed', 'completed', 'completed', 'completed', 'completed', 'completed']),
        }),
    },
}

export const Failed: Story = {
    args: {
        mode: 'cloud',
        elapsedSeconds: 312,
        progress: progress({
            phase: 'error',
            steps: cloudSteps(['completed', 'completed', 'failed', 'pending', 'pending', 'pending']),
            error: { title: 'Setup hit a snag', detail: 'The setup wizard could not finish.' },
        }),
    },
}

// Every state in one canvas, for side-by-side review (GROW-98). Reuses the individual stories' args so
// there is a single source of truth for each fixture.
export const AllStates: Story = {
    parameters: { controls: { disable: true } },
    render: () => {
        const states: { label: string; args: Story['args'] }[] = [
            { label: 'Connecting', args: Connecting.args },
            { label: 'Cloud, wizard running', args: CloudWizardRunning.args },
            { label: 'Cloud, keeping CI green', args: CloudKeepingCiGreen.args },
            { label: 'Local, running', args: LocalRunning.args },
            { label: 'Completed', args: Completed.args },
            { label: 'Failed', args: Failed.args },
        ]
        return (
            <div className="flex flex-col gap-5 items-end">
                {states.map(({ label, args }) => (
                    <div key={label} className="flex flex-col gap-1 items-end">
                        <span className="text-xs text-muted">{label}</span>
                        <WizardSyncCard
                            progress={args!.progress!}
                            elapsedSeconds={args!.elapsedSeconds!}
                            mode={args!.mode!}
                            onExpand={() => {}}
                            onDismiss={() => {}}
                        />
                    </div>
                ))}
            </div>
        )
    },
}

// Configure the card live from the controls panel (GROW-98): pick phase, mode, how many steps are done,
// the current task label, and elapsed, and the fixture is built from those.
interface PlaygroundArgs {
    phase: InstallationProgress['phase']
    mode: WizardSyncMode
    elapsedSeconds: number
    completedSteps: number
    currentTask: string
}

export const Playground: StoryObj<PlaygroundArgs> = {
    argTypes: {
        phase: { control: 'select', options: ['connecting', 'running', 'completed', 'error'] },
        mode: { control: 'inline-radio', options: ['cloud', 'local'] },
        elapsedSeconds: { control: { type: 'number', min: 0 } },
        completedSteps: { control: { type: 'range', min: 0, max: 6 } },
        currentTask: { control: 'text' },
    },
    args: { phase: 'running', mode: 'cloud', elapsedSeconds: 134, completedSteps: 2, currentTask: 'Capturing events' },
    render: (args) => {
        const statuses: InstallationStepStatus[] = [0, 1, 2, 3, 4, 5].map((i) =>
            i < args.completedSteps ? 'completed' : i === args.completedSteps ? 'in_progress' : 'pending'
        )
        const built = progress({
            phase: args.phase,
            steps: cloudSteps(
                statuses,
                args.currentTask ? { at: args.completedSteps, text: args.currentTask } : undefined
            ),
            prUrl: args.phase === 'completed' ? 'https://github.com/acme-co/web/pull/42' : null,
            error: args.phase === 'error' ? { title: 'Setup hit a snag', detail: 'Something stopped the run.' } : null,
        })
        return (
            <WizardSyncCard
                progress={built}
                elapsedSeconds={args.elapsedSeconds}
                mode={args.mode}
                onExpand={() => {}}
                onDismiss={() => {}}
            />
        )
    },
}
