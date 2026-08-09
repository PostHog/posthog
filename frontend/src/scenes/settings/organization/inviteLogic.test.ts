import { MOCK_DEFAULT_ORGANIZATION_INVITE } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { organizationLogic } from 'scenes/organizationLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { OrganizationInviteType } from '~/types'

import { inviteLogic } from './inviteLogic'

const PHANTOM_INVITE: OrganizationInviteType = {
    ...MOCK_DEFAULT_ORGANIZATION_INVITE,
    id: '00000000-0000-0000-0000-000000000001',
    target_email: 'phantom@example.com',
}
const LIVE_INVITE: OrganizationInviteType = {
    ...MOCK_DEFAULT_ORGANIZATION_INVITE,
    id: '00000000-0000-0000-0000-000000000002',
    target_email: 'live@example.com',
}

describe('inviteLogic', () => {
    let logic: ReturnType<typeof inviteLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/organizations/:organization_id/invites/': () => [
                    200,
                    { count: 2, next: null, previous: null, results: [PHANTOM_INVITE, LIVE_INVITE] },
                ],
            },
        })
        initKeaTests()
        await expectLogic(organizationLogic).toFinishAllListeners()
        logic = inviteLogic()
        logic.mount()
        logic.actions.loadInvites()
        await expectLogic(logic).toDispatchActions(['loadInvitesSuccess'])
    })

    it('drops a row and resyncs when the server already removed the invite (404)', async () => {
        useMocks({
            delete: {
                '/api/organizations/:organization_id/invites/:id/': () => [404, { detail: 'Not found.' }],
            },
        })

        // The 404 must not surface as a loader failure; it is resolved as a successful removal.
        await expectLogic(logic, () => {
            logic.actions.deleteInvite(PHANTOM_INVITE)
        })
            .toDispatchActions(['deleteInvite', 'deleteInviteSuccess', 'loadInvites'])
            .toNotHaveDispatchedActions(['deleteInviteFailure'])

        expect(logic.values.invites.map((invite) => invite.id)).not.toContain(PHANTOM_INVITE.id)
    })

    it('resyncs from the server after a successful cancel', async () => {
        useMocks({
            delete: {
                '/api/organizations/:organization_id/invites/:id/': () => [204],
            },
        })

        await expectLogic(logic, () => {
            logic.actions.deleteInvite(LIVE_INVITE)
        }).toDispatchActions(['deleteInviteSuccess', 'loadInvites'])
    })
})
