import { expectLogic } from 'kea-test-utils'

import { verifyEmailLogic } from 'scenes/authentication/verify-email/verifyEmailLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

describe('verifyEmailLogic', () => {
    let logic: ReturnType<typeof verifyEmailLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = verifyEmailLogic()
        logic.mount()
        logic.actions.setUuid('12345678')
    })

    afterEach(() => logic.unmount())

    it('empties the code and reports the error when the server rejects it', async () => {
        useMocks({
            post: {
                '/api/users/verify_email/': () => [400, { code: 'invalid_code', detail: 'That code is wrong.' }],
            },
        })
        logic.actions.setVerificationCode('123456')

        await expectLogic(logic, () => logic.actions.submitVerificationCode())
            .toFinishAllListeners()
            .toMatchValues({ verificationCode: '', verificationCodeError: 'That code is wrong.' })
    })

    it('names the stored address only when its uuid matches the page uuid', () => {
        localStorage.setItem(
            'ph_pending_verification_email',
            JSON.stringify({ uuid: '12345678', email: 'signup@example.com' })
        )
        expect(logic.values.pendingEmail).toEqual('signup@example.com')

        logic.actions.setUuid('another-account')
        expect(logic.values.pendingEmail).toEqual(null)
    })

    it('keeps a partial code when it is too short to send', async () => {
        logic.actions.setVerificationCode('123')

        await expectLogic(logic, () => logic.actions.submitVerificationCode())
            .toFinishAllListeners()
            .toMatchValues({
                verificationCode: '123',
                verificationCodeError: 'Enter the 6-digit code from your email.',
            })
    })
})
