import { router } from 'kea-router'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { verifyEmailLogic } from './verifyEmailLogic'
import { verifyEmailTelemetryLogic } from './verifyEmailTelemetryLogic'

jest.mock('posthog-js')

function capturedProperties(event: string): Record<string, any> | undefined {
    return (posthog.capture as jest.Mock).mock.calls.find(([name]) => name === event)?.[1]
}

function captureCount(event: string): number {
    return (posthog.capture as jest.Mock).mock.calls.filter(([name]) => name === event).length
}

describe('verifyEmailTelemetryLogic', () => {
    let logic: ReturnType<typeof verifyEmailTelemetryLogic.build>

    beforeEach(() => {
        initKeaTests()
        verifyEmailLogic().mount()
        router.actions.push('/verify_email/abc-123')
        jest.mocked(posthog.capture).mockClear()
        logic = verifyEmailTelemetryLogic()
        logic.mount()
    })

    afterEach(() => {
        if (logic.isMounted()) {
            logic.unmount()
        }
    })

    it('reports the arrival that the send event cannot see', () => {
        expect(capturedProperties('email verification page viewed')).toMatchObject({
            code_sent: true,
            deep_link_reason: null,
        })
    })

    it('counts a rejected code but not the clearing of its error', () => {
        verifyEmailLogic.actions.setVerificationCodeError('Nope.')
        verifyEmailLogic.actions.setVerificationCodeError(null)

        expect(captureCount('email verification failed')).toBe(1)
        expect(logic.values.failedAttempts).toBe(1)
    })

    it('closes the funnel once, with what the person tried first', () => {
        verifyEmailLogic.actions.requestVerificationCode('abc-123')
        verifyEmailLogic.actions.setVerificationCodeError('Nope.')
        logic.actions.reportHelpOpened()
        window.dispatchEvent(new Event('pagehide'))
        logic.unmount()

        expect(captureCount('email verification exited')).toBe(1)
        expect(capturedProperties('email verification exited')).toMatchObject({
            outcome: 'left',
            resends: 1,
            failed_attempts: 1,
            help_opened: true,
        })
    })

    it('holds the exit while the page rests in the back-forward cache', () => {
        window.dispatchEvent(Object.assign(new Event('pagehide'), { persisted: true }))

        expect(captureCount('email verification exited')).toBe(0)

        verifyEmailLogic.actions.submitVerificationCodeSuccess({ success: true, uuid: 'abc-123' })
        logic.unmount()

        expect(capturedProperties('email verification exited')).toMatchObject({ outcome: 'verified' })
    })

    it('reports a second visit after the scene remounts', () => {
        window.dispatchEvent(new Event('pagehide'))
        logic.unmount()
        jest.mocked(posthog.capture).mockClear()

        logic = verifyEmailTelemetryLogic()
        logic.mount()
        logic.unmount()

        expect(captureCount('email verification exited')).toBe(1)
    })

    it('separates a verified exit from an abandoned one', () => {
        verifyEmailLogic.actions.submitVerificationCodeSuccess({ success: true, uuid: 'abc-123' })
        logic.unmount()

        expect(capturedProperties('email verification exited')).toMatchObject({ outcome: 'verified' })
    })
})
