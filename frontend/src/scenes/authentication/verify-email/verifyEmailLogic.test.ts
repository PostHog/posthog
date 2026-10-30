import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { verifyEmailLogic } from './verifyEmailLogic'

jest.mock('posthog-js')

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

    it('reports the verify email step once the deep link opens', async () => {
        router.actions.push('/verify_email/abc-123')

        await waitFor(() =>
            expect(posthog.capture).toHaveBeenCalledWith(
                'auth step viewed',
                expect.objectContaining({ step: 'verify_email', entry: null })
            )
        )
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
