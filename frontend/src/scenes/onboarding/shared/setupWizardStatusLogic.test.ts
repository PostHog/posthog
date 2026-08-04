import { statusFromProgress } from './setupWizardStatusLogic'
import type { InstallationProgress } from './wizard-sync/installationProgressLogic'

function progress(overrides: Partial<InstallationProgress>): InstallationProgress {
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

describe('statusFromProgress', () => {
    it.each([
        ['open PR', false],
        ['merged PR', true],
    ])('propagates prMerged from the live stream for a %s', (_name, prMerged) => {
        const status = statusFromProgress(progress({ prUrl: 'https://github.com/org/repo/pull/1', prMerged }))
        expect(status).toEqual({
            kind: 'pull_request',
            pullRequest: { url: 'https://github.com/org/repo/pull/1', merged: prMerged },
        })
    })
})
