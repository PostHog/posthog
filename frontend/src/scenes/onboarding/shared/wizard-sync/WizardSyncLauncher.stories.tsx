import type { Meta, StoryObj } from '@storybook/react'

import type { InstallationProgress } from './installationProgressLogic'
import { WizardSyncLauncher } from './WizardSyncLauncher'

function progress(overrides: Partial<InstallationProgress> = {}): InstallationProgress {
    return {
        phase: 'running',
        steps: [],
        error: null,
        prUrl: null,
        prMerged: false,
        isCurrent: true,
        pendingInput: null,
        startedBy: null,
        handoffText: null,
        ...overrides,
    }
}

const meta: Meta<typeof WizardSyncLauncher> = {
    title: 'Scenes-Other/Onboarding/Shared/Wizard Sync Launcher',
    component: WizardSyncLauncher,
    tags: ['autodocs'],
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<typeof WizardSyncLauncher>

export const Running: Story = {
    args: { progress: progress(), elapsedSeconds: 96, onRestore: () => {} },
}

// What a run that stopped reporting looks like away from the setup scenes: a pill, not a panel.
export const LostContact: Story = {
    args: {
        progress: progress({
            phase: 'error',
            error: {
                title: 'Setup lost contact',
                detail: 'We stopped hearing back from this run.',
                kind: 'lost_contact',
            },
        }),
        elapsedSeconds: 640,
        stale: true,
        onRestore: () => {},
    },
}
