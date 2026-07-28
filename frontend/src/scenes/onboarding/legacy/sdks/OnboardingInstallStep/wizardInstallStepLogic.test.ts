import { getContext } from 'kea'
import posthog from 'posthog-js'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { initKeaTests } from '~/test/init'

import { ESCAPE_HATCH_TIMEOUT_MS, wizardInstallStepLogic } from './wizardInstallStepLogic'

const FAILED_CLOUD_RUN = {
    taskId: 'task-1',
    runId: 'run-1',
    status: 'failed' as const,
    durationSeconds: 10,
    prOpened: false,
    prUrl: null,
}

describe('wizardInstallStepLogic', () => {
    let logic: ReturnType<typeof wizardInstallStepLogic.build>
    let captureSpy: jest.SpyInstance

    const capturesOf = (event: string): any[][] => captureSpy.mock.calls.filter(([name]) => name === event)
    const fireLocalSessionFinished = (outcome: string): void => {
        // Raw dispatch: mounting the giant eventUsageLogic just to fire one action would drag its
        // whole connection tree into the test.
        getContext().store.dispatch({
            type: eventUsageLogic.actionTypes.reportWizardSyncSessionFinished,
            payload: { outcome },
        })
    }

    beforeEach(() => {
        initKeaTests()
        jest.useFakeTimers()
        captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        jest.spyOn(posthog, 'getFeatureFlagResult').mockReturnValue(undefined)
        logic = wizardInstallStepLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('reveals with the timeout trigger once the deadline elapses', () => {
        logic.actions.armEscapeHatch()
        jest.advanceTimersByTime(ESCAPE_HATCH_TIMEOUT_MS - 1)
        expect(logic.values.escapeHatchRevealed).toBe(false)

        jest.advanceTimersByTime(1)

        expect(logic.values.escapeHatchTrigger).toBe('timeout')
        expect(capturesOf('onboarding install escape hatch shown')).toHaveLength(1)
        expect(capturesOf('onboarding install escape hatch shown')[0][1]).toMatchObject({ trigger: 'timeout' })
    })

    it('re-arming keeps the original deadline instead of restarting the countdown', () => {
        // The shell's effect re-fires armEscapeHatch on prop changes; a restart would push the
        // reveal out indefinitely.
        logic.actions.armEscapeHatch()
        jest.advanceTimersByTime(ESCAPE_HATCH_TIMEOUT_MS / 2)
        logic.actions.armEscapeHatch()
        jest.advanceTimersByTime(ESCAPE_HATCH_TIMEOUT_MS / 2)

        expect(logic.values.escapeHatchTrigger).toBe('timeout')
    })

    it('disarming cancels the pending timeout', () => {
        // Installation completing disarms the hatch; a live timer would still reveal it afterwards.
        logic.actions.armEscapeHatch()
        logic.actions.disarmEscapeHatch()
        jest.advanceTimersByTime(ESCAPE_HATCH_TIMEOUT_MS * 2)

        expect(logic.values.escapeHatchRevealed).toBe(false)
    })

    it.each([
        [
            'a failed cloud run',
            () => logic.actions.reportContextOnboardingCloudRunCompleted(FAILED_CLOUD_RUN),
            'cloud_run_failed',
        ],
        ['an errored local wizard session', () => fireLocalSessionFinished('error'), 'local_session_error'],
    ])('reveals immediately on %s while armed', (_name, fire, expectedTrigger) => {
        logic.actions.armEscapeHatch()
        fire()

        expect(logic.values.escapeHatchTrigger).toBe(expectedTrigger)
    })

    it('ignores wizard failures when not armed, so nothing leaks outside the test arm', () => {
        logic.actions.reportContextOnboardingCloudRunCompleted(FAILED_CLOUD_RUN)
        fireLocalSessionFinished('error')

        expect(logic.values.escapeHatchRevealed).toBe(false)
        expect(capturesOf('onboarding install escape hatch shown')).toHaveLength(0)
    })

    it('does not treat a cancelled cloud run as a failure trigger', () => {
        // Cancelling is the user's own action; the timeout still covers them if they stall.
        logic.actions.armEscapeHatch()
        logic.actions.reportContextOnboardingCloudRunCompleted({ ...FAILED_CLOUD_RUN, status: 'cancelled' })

        expect(logic.values.escapeHatchRevealed).toBe(false)
    })

    it('keeps the first trigger and reports shown only once', () => {
        logic.actions.armEscapeHatch()
        jest.advanceTimersByTime(ESCAPE_HATCH_TIMEOUT_MS)
        logic.actions.reportContextOnboardingCloudRunCompleted(FAILED_CLOUD_RUN)

        expect(logic.values.escapeHatchTrigger).toBe('timeout')
        expect(capturesOf('onboarding install escape hatch shown')).toHaveLength(1)
    })

    it('clicking the hatch opens the manual modal and reports the escape-hatch surface', () => {
        logic.actions.armEscapeHatch()
        jest.advanceTimersByTime(ESCAPE_HATCH_TIMEOUT_MS)
        logic.actions.clickEscapeHatch()

        expect(logic.values.manualModalOpen).toBe(true)
        expect(capturesOf('onboarding install escape hatch clicked')).toHaveLength(1)
        expect(capturesOf('onboarding manual setup opened')[0][1]).toMatchObject({ surface: 'escape_hatch' })
    })
})
