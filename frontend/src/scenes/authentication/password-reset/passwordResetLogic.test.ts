import { expectLogic } from 'kea-test-utils'

import { passwordResetLogic } from 'scenes/authentication/password-reset/passwordResetLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

describe('passwordResetLogic', () => {
    let logic: ReturnType<typeof passwordResetLogic.build>
    let resetRequestCount: number

    beforeEach(() => {
        resetRequestCount = 0
        useMocks({
            post: {
                '/api/login/precheck': async ({ request }) => {
                    const { email } = (await request.json()) as { email: string }
                    return [
                        200,
                        email.endsWith('@sso-enforced.com')
                            ? { sso_enforcement: 'google-oauth2', saml_available: false }
                            : { sso_enforcement: null, saml_available: false },
                    ]
                },
                '/api/reset/': () => {
                    resetRequestCount += 1
                    return [200, {}]
                },
            },
        })
        initKeaTests()
        logic = passwordResetLogic()
        logic.mount()
    })

    it('surfaces SSO enforcement from the precheck', async () => {
        await expectLogic(logic, () => {
            logic.actions.precheck({ email: 'someone@sso-enforced.com' })
        })
            .toDispatchActions(['precheckSuccess'])
            .toMatchValues({
                precheckResponse: expect.objectContaining({ sso_enforcement: 'google-oauth2', status: 'completed' }),
            })
    })

    it('does not flag SSO for a non-enforced domain', async () => {
        await expectLogic(logic, () => {
            logic.actions.precheck({ email: 'someone@example.com' })
        })
            .toDispatchActions(['precheckSuccess'])
            .toMatchValues({
                precheckResponse: expect.objectContaining({ sso_enforcement: null, status: 'completed' }),
            })
    })

    it('skips the reset request when SSO is enforced', async () => {
        await expectLogic(logic, () => {
            logic.actions.precheck({ email: 'someone@sso-enforced.com' })
        }).toDispatchActions(['precheckSuccess'])

        await expectLogic(logic, () => {
            logic.actions.setRequestPasswordResetValue('email', 'someone@sso-enforced.com')
            logic.actions.submitRequestPasswordReset()
        }).toDispatchActions(['submitRequestPasswordResetSuccess'])

        expect(resetRequestCount).toEqual(0)
    })

    it('sends the reset request when SSO is not enforced', async () => {
        await expectLogic(logic, () => {
            logic.actions.precheck({ email: 'someone@example.com' })
        }).toDispatchActions(['precheckSuccess'])

        await expectLogic(logic, () => {
            logic.actions.setRequestPasswordResetValue('email', 'someone@example.com')
            logic.actions.submitRequestPasswordReset()
        }).toDispatchActions(['submitRequestPasswordResetSuccess'])

        expect(resetRequestCount).toEqual(1)
    })
})
