import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { inviteLogic } from './inviteLogic'

type InviteLogic = ReturnType<typeof inviteLogic.build>

describe('inviteLogic', () => {
    let logic: InviteLogic

    const fillDraft = (): void => {
        logic.actions.showInviteModal()
        logic.actions.updateInviteAtIndex({ target_email: 'first@example.com', first_name: 'First' }, 0)
        logic.actions.appendInviteRow()
        logic.actions.updateInviteAtIndex({ target_email: 'second@example.com' }, 1)
        logic.actions.updateMessage('Come and join us')
    }

    /** What an SSO re-authentication does to the app: the page unloads and everything is built again. */
    const reloadPage = (): void => {
        logic.unmount()
        initKeaTests()
        logic = inviteLogic.build()
        logic.mount()
    }

    beforeEach(() => {
        // The draft is persisted to localStorage, which jsdom keeps alive across tests in this file.
        localStorage.clear()
        useMocks({
            get: {
                '/api/organizations/:organization_id/invites/': { count: 0, results: [] },
            },
            post: {
                '/api/organizations/:organization_id/invites/bulk/': [
                    { id: 'invite-1', target_email: 'first@example.com' },
                    { id: 'invite-2', target_email: 'second@example.com' },
                ],
            },
        })
        initKeaTests()
        logic = inviteLogic.build()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('keeps the draft when the page reloads for re-authentication', () => {
        fillDraft()

        reloadPage()

        expect(logic.values.invitesToSend.map((invite) => invite.target_email)).toEqual([
            'first@example.com',
            'second@example.com',
        ])
        expect(logic.values.invitesToSend[0].first_name).toEqual('First')
        expect(logic.values.message).toEqual('Come and join us')
    })

    it.each([
        [
            'the modal closes',
            (currentLogic: InviteLogic): Promise<void> => {
                currentLogic.actions.hideInviteModal()
                return Promise.resolve()
            },
        ],
        [
            'the invites are sent',
            async (currentLogic: InviteLogic): Promise<void> => {
                await expectLogic(currentLogic, () => {
                    currentLogic.actions.inviteTeamMembers()
                })
                    .toDispatchActions(['inviteTeamMembersSuccess'])
                    .toFinishAllListeners()
            },
        ],
    ])('drops the draft when %s', async (_, clearDraft) => {
        fillDraft()

        await clearDraft(logic)

        reloadPage()

        expect(logic.values.invitesToSend.map((invite) => invite.target_email)).toEqual([''])
        expect(logic.values.message).toEqual('')
    })
})
