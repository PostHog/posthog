import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { passwordResetLogic } from './passwordResetLogic'

const UUID = 'user-uuid-3f32'
const TOKEN = 'a-valid-looking-token'
const STRONG_PASSWORD = 'dr0wssap-gnorts-yrev'

describe('passwordResetLogic', () => {
    let logic: ReturnType<typeof passwordResetLogic.build>

    const submitNewPassword = async (): Promise<void> => {
        router.actions.push(`/reset/${UUID}/${TOKEN}`)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setPasswordResetValues({ password: STRONG_PASSWORD, passwordConfirm: STRONG_PASSWORD })
        await expectLogic(logic, () => {
            logic.actions.submitPasswordReset()
        }).toFinishAllListeners()
    }

    beforeEach(() => {
        initKeaTests()
        logic = passwordResetLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    // A token can die between opening the link and submitting the form — the page sits open past the
    // expiry, or a newer link supersedes it. The submit response is then the only place the cause
    // shows up, so it has to reach the same value the initial check writes.
    it.each([
        ['password_already_reset', 'You already used this link to change your password.'],
        ['expired_token', 'This reset link expired.'],
        ['superseded_token', 'A newer reset link was sent to your email.'],
        ['invalid_token', 'This reset link is not valid.'],
    ])('reports a %s failure on submit as a failed token', async (code, detail) => {
        useMocks({
            get: { [`/api/reset/${UUID}/`]: { success: true } },
            post: {
                [`/api/reset/${UUID}/`]: () => [400, { type: 'validation_error', code, detail, attr: 'token' }],
            },
        })

        await submitNewPassword()

        expect(logic.values.validatedResetToken).toEqual({
            success: false,
            errorCode: code,
            errorDetail: detail,
        })
    })

    it('keeps the form when the password itself is rejected', async () => {
        useMocks({
            get: { [`/api/reset/${UUID}/`]: { success: true } },
            post: {
                [`/api/reset/${UUID}/`]: () => [
                    400,
                    {
                        type: 'validation_error',
                        code: 'password_too_short',
                        detail: 'This password is too short.',
                        attr: 'password',
                    },
                ],
            },
        })

        await submitNewPassword()

        expect(logic.values.validatedResetToken).toEqual({ success: true, token: TOKEN, uuid: UUID })
        expect(logic.values.passwordResetManualErrors).toEqual({ password: 'This password is too short.' })
    })
})
