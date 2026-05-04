import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { inviteSignupLogic } from './inviteSignupLogic'

describe('inviteSignupLogic — fromSignupRedirect flag', () => {
    let logic: ReturnType<typeof inviteSignupLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/signup/invite-123/': () => [400, { code: 'invalid_invite' }],
            },
        })
        initKeaTests()
        logic = inviteSignupLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('sets fromSignupRedirect=true when from_signup_redirect=1 is in URL', async () => {
        router.actions.push('/signup/invite-123/', { from_signup_redirect: '1' })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.fromSignupRedirect).toBe(true)
    })

    it('sets fromSignupRedirect=false when query param is absent', async () => {
        router.actions.push('/signup/invite-123/')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.fromSignupRedirect).toBe(false)
    })
})
