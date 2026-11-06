import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { passwordResetLogic } from './passwordResetLogic'

describe('passwordResetLogic', () => {
    let logic: ReturnType<typeof passwordResetLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/reset/:uuid/': () => [
                    400,
                    { code: 'invalid_token', detail: 'This reset token is invalid or has expired.' },
                ],
            },
        })
        initKeaTests()
        logic = passwordResetLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([
        ['passwords that do not match', 'hedgE-hog-123%', '1234567A', 'passwordConfirm', 'Passwords do not match'],
        ['a password under 8 characters', '123', '123', 'password', 'Must be at least 8 characters long'],
    ])('rejects %s', (_name, password, passwordConfirm, field, error) => {
        logic.actions.setPasswordResetValues({ password, passwordConfirm })

        expect(logic.values.passwordResetValidationErrors).toMatchObject({ [field]: error })
    })

    it('marks the reset link invalid when the API rejects its token', async () => {
        router.actions.push('/reset/invalid_user/token')

        await expectLogic(logic).toDispatchActions(['validateResetTokenSuccess'])
        expect(logic.values.validatedResetToken).toMatchObject({ success: false })
        expect(logic.values.validatedResetToken?.token).toBeUndefined()
    })
})
