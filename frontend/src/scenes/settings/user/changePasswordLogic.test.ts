import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { changePasswordLogic } from './changePasswordLogic'

describe('changePasswordLogic', () => {
    let logic: ReturnType<typeof changePasswordLogic.build>
    let resetRequests: Record<string, any>[]

    beforeEach(() => {
        resetRequests = []
        useMocks({
            post: {
                '/api/reset/': async ({ request }) => {
                    resetRequests.push((await request.json()) as Record<string, any>)
                    return [204, null]
                },
            },
        })
        initKeaTests()
        logic = changePasswordLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('sends the reset link to the signed-in user without asking for their address', async () => {
        logic.actions.requestPasswordResetEmail()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ passwordResetEmailSent: true })
        expect(resetRequests).toEqual([{ email: MOCK_DEFAULT_USER.email }])
    })

    it('explains why no link arrived when the reset is refused', async () => {
        jest.spyOn(lemonToast, 'error')
        useMocks({
            post: {
                '/api/reset/': () => [
                    400,
                    { type: 'validation_error', code: 'sso_enforced', detail: 'SSO login is enforced.' },
                ],
            },
        })

        logic.actions.requestPasswordResetEmail()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ passwordResetEmailSent: false })
        expect(lemonToast.error).toHaveBeenCalledWith('SSO login is enforced.')
    })
})
