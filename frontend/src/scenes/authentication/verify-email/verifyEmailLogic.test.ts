import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

import { verifyEmailLogic } from './verifyEmailLogic'

const UNVERIFIED_USER = { ...MOCK_DEFAULT_USER, is_email_verified: false }

describe('verifyEmailLogic', () => {
    let logic: ReturnType<typeof verifyEmailLogic.build>

    afterEach(() => {
        logic?.unmount()
        window.POSTHOG_APP_CONTEXT = undefined
    })

    it('ignores a route re-match while a validation is already in flight', async () => {
        // A never-resolving verify keeps the run in flight (loading stays true) without
        // advancing any timer, mirroring the window where the success breakpoint is pending.
        useMocks({
            get: { '/api/users/@me/': () => [200, { is_email_verified: false }] },
            post: { '/api/users/verify_email/': () => new Promise(() => {}) },
        })
        initKeaTests()
        router.actions.push('/verify_email/uuid-1/token-1')
        logic = verifyEmailLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['validateEmailToken'])
        expect(logic.values.validatedEmailTokenLoading).toBe(true)
        expect(logic.values.view).toBe('verify')

        // urlToAction runs synchronously on a location change. Re-matching the token route
        // mid-flight must be skipped — a re-dispatch would cancel the in-flight breakpoint and
        // reset the view back to 'verify'. We land on the bare /verify_email route first so a
        // broken guard would be observable as the view flipping back to 'verify'.
        router.actions.push('/verify_email')
        expect(logic.values.view).toBe('invalid')
        // A broken guard would synchronously run setView('verify') here, flipping the view back.
        router.actions.push('/verify_email/uuid-1/token-1')
        expect(logic.values.view).toBe('invalid')
    })

    it('resolves to a defined result and shows the invalid view when the token is rejected', async () => {
        useMocks({
            get: { '/api/users/@me/': () => [200, UNVERIFIED_USER] },
            post: { '/api/users/verify_email/': () => [400, { code: 'invalid_token', detail: 'Invalid token' }] },
        })
        // The catch treats an already-verified user as success, so bootstrap an unverified one to
        // exercise the invalid-token branch (initKeaTests preserves a current_user set here).
        window.POSTHOG_APP_CONTEXT = { current_user: UNVERIFIED_USER } as unknown as AppContext
        initKeaTests()
        router.actions.push('/verify_email/uuid-1/bad-token')
        logic = verifyEmailLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['validateEmailTokenSuccess']).toFinishAllListeners()

        expect(logic.values.view).toBe('invalid')
        // The success reducer must never receive `undefined` — that trips kea's reducer guard.
        expect(logic.values.validatedEmailToken).toEqual({
            success: false,
            errorCode: 'invalid_token',
            errorDetail: 'Invalid token',
        })
    })
})
