import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ErrorCodes, inviteSignupLogic } from './inviteSignupLogic'

describe('inviteSignupLogic', () => {
    let logic: ReturnType<typeof inviteSignupLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/signup/expired-invite/': () => [
                    400,
                    { type: 'validation_error', code: 'expired', detail: 'This invite has expired.', attr: null },
                ],
            },
            post: {
                '/api/signup/request-invite': () => [200, { requested: true }],
            },
        })
        initKeaTests()
        logic = inviteSignupLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('routes an expired invite to the InviteExpired state so the recovery button shows', async () => {
        logic.actions.setInviteId('expired-invite')
        logic.actions.prevalidateInvite('expired-invite')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.error?.code).toBe(ErrorCodes.InviteExpired)
    })

    it('requestNewInvite posts to the request-invite endpoint and flags the request as sent', async () => {
        logic.actions.setInviteId('expired-invite')
        logic.actions.requestNewInvite()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.newInviteRequested).toBe(true)
    })
})
