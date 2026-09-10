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
                    { code: 'expired', detail: 'This invite has expired. Please ask your admin for a new one.' },
                ],
                '/api/signup/used-invite/': () => [
                    400,
                    { code: 'invalid', detail: 'The provided invite ID is not valid.' },
                ],
            },
        })
        initKeaTests()
        logic = inviteSignupLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([
        ['expired-invite', ErrorCodes.InviteExpired],
        ['used-invite', ErrorCodes.InvalidInvite],
    ])('tells an expired invite apart from one that no longer exists: %s', async (inviteId, expectedCode) => {
        logic.actions.prevalidateInvite(inviteId)

        await expectLogic(logic).toDispatchActions(['prevalidateInviteSuccess'])
        expect(logic.values.error?.code).toEqual(expectedCode)
    })
})
