import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import type { InstallationErrorKind, InstallationProgress } from './installationProgressLogic'
import { WizardSyncSurface } from './WizardSyncSurface'

function errorProgress(kind: InstallationErrorKind): InstallationProgress {
    return {
        phase: 'error',
        steps: [],
        error: { title: 'Setup lost contact', detail: 'We stopped hearing back from this run.', kind },
        prUrl: null,
        prMerged: false,
        isCurrent: true,
        pendingInput: null,
        startedBy: null,
        handoffText: null,
    }
}

function renderOn(scene: Scene, progress: InstallationProgress, onClear = jest.fn()): jest.Mock {
    sceneLogic.actions.setScene(scene, undefined, { params: {}, searchParams: {}, hashParams: {} })
    render(
        <Provider>
            <WizardSyncSurface
                progress={progress}
                startedAt={new Date().toISOString()}
                mode="cloud"
                runKey="run-1"
                onClear={onClear}
            />
        </Provider>
    )
    return onClear as jest.Mock
}

describe('WizardSyncSurface', () => {
    beforeEach(() => {
        initKeaTests()
        userLogic.mount()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        sceneLogic.mount()
    })

    // This suite does not get testing-library's automatic teardown, so a tree left behind would
    // still answer the next test's queries.
    afterEach(() => {
        cleanup()
    })

    // The reported symptom: a run that stopped reporting put a red panel over the Inbox, which has
    // nothing to do with setup. It must collapse to the pill there, and stay a full card where
    // setup is the reason the person is on the page.
    it.each([
        [Scene.Inbox, 'launcher'],
        [Scene.Onboarding, 'card'],
    ])('shows a lost-contact run as the %s on %s', (scene, expected) => {
        renderOn(scene as Scene, errorProgress('lost_contact'))
        expect(!!screen.queryByTestId('wizard-sync-launcher')).toBe(expected === 'launcher')
    })

    // Only the lost-contact case collapses: a run that reported its own failure has something the
    // user can act on, so it keeps the card everywhere.
    it('keeps the card for a reported failure off the setup scenes', () => {
        renderOn(Scene.Inbox, errorProgress('failed'))
        expect(screen.queryByTestId('wizard-sync-launcher')).toBeNull()
    })

    it('retires a lost-contact run instead of parking it in the corner', () => {
        jest.useFakeTimers()
        try {
            const onClear = renderOn(Scene.Inbox, errorProgress('lost_contact'))
            expect(onClear).not.toHaveBeenCalled()
            jest.advanceTimersByTime(5 * 60 * 1000)
            expect(onClear).toHaveBeenCalledTimes(1)
        } finally {
            jest.useRealTimers()
        }
    })
})
