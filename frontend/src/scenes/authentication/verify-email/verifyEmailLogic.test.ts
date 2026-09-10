import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { verifyEmailLogic } from './verifyEmailLogic'

describe('verifyEmailLogic', () => {
    let logic: ReturnType<typeof verifyEmailLogic.build>

    beforeEach(() => {
        useMocks({
            post: {
                '/api/users/request_email_verification/': () => [
                    400,
                    { code: 'already_verified', detail: 'Email is already verified.' },
                ],
            },
        })
        initKeaTests()
        logic = verifyEmailLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('reads the deep-link reason the login redirect sent', async () => {
        router.actions.push('/verify_email/abc-123', { reason: 'stripe_deep_link' })

        await expectLogic(logic).toMatchValues({
            view: 'pending',
            uuid: 'abc-123',
            reason: 'stripe_deep_link',
            verificationEmailSent: true,
        })
    })

    it.each([['unknown_partner'], ['']])('ignores a reason it does not know: %s', async (reason) => {
        router.actions.push('/verify_email/abc-123', { reason })

        await expectLogic(logic).toMatchValues({ reason: null })
    })

    it('sends an already verified account to log in instead of reporting a failure', async () => {
        router.actions.push('/verify_email/abc-123')

        logic.actions.requestVerificationCode('abc-123')

        await expectLogic(logic)
            .toDispatchActions(['requestVerificationCodeSuccess'])
            .toMatchValues({ newlyRequestedVerificationCode: false })
        expect(router.values.location.pathname).toEqual('/login')
    })

    it('flags a verification email the login could not send', async () => {
        router.actions.push('/verify_email/abc-123', { reason: 'stripe_deep_link', email_sent: 'false' })

        await expectLogic(logic).toMatchValues({ verificationEmailSent: false })
    })
})
