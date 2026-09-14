import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ErrorCodes, inviteSignupLogic } from './inviteSignupLogic'

describe('inviteSignupLogic', () => {
    let logic: ReturnType<typeof inviteSignupLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = inviteSignupLogic()
        logic.mount()
    })

    // A blocked organization must keep its own code. The invalid-invite bucket tells the user the
    // link is invalid or expired and to ask for a new invite, and a new invite hits the same block.
    it.each([
        ['organization_deactivated', ErrorCodes.OrganizationDeactivated],
        ['organization_pending_deletion', ErrorCodes.OrganizationPendingDeletion],
        ['no_such_reason', ErrorCodes.InvalidInvite],
    ])('prevalidation refused with %s sets the matching error code', async (serverCode, expectedCode) => {
        useMocks({
            get: {
                '/api/signup/:id/': () => [400, { type: 'validation_error', code: serverCode, detail: 'Refused.' }],
            },
        })

        await expectLogic(logic, () => {
            logic.actions.prevalidateInvite('7bd7b4c6-4b3f-4c1f-9b2a-2f0d4a6c8e10')
        })
            .toFinishAllListeners()
            .toMatchValues({ error: { code: expectedCode, detail: 'Refused.' } })
    })
})
