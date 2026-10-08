import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { verifyEmailLogic } from './verifyEmailLogic'

describe('verifyEmailLogic', () => {
    let logic: ReturnType<typeof verifyEmailLogic.build>

    beforeEach(() => {
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

    it('flags a verification email the login could not send', async () => {
        router.actions.push('/verify_email/abc-123', { reason: 'stripe_deep_link', email_sent: 'false' })

        await expectLogic(logic).toMatchValues({ verificationEmailSent: false })
    })
})
