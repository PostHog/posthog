import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { inviteLogic } from './inviteLogic'

describe('inviteLogic', () => {
    let logic: ReturnType<typeof inviteLogic.build>

    beforeEach(() => {
        // The draft is persisted to session storage, which jsdom keeps across tests in this file.
        sessionStorage.clear()
        initKeaTests()
        logic = inviteLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('keeps typed rows when the modal is hidden', async () => {
        await expectLogic(logic, () => {
            logic.actions.updateInviteAtIndex({ target_email: 'sam@example.com' }, 0)
            logic.actions.hideInviteModal()
        }).toMatchValues({
            invitesToSend: [expect.objectContaining({ target_email: 'sam@example.com' })],
        })
    })

    it('restores the draft after a remount, as the OAuth re-authentication redirect forces', async () => {
        await expectLogic(logic, () => {
            logic.actions.updateInviteAtIndex({ target_email: 'sam@example.com', first_name: 'Sam' }, 0)
            logic.actions.updateMessage('join us')
            logic.actions.setInviteConfirmationText('send invites')
        }).toFinishAllListeners()

        logic.unmount()
        logic = inviteLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({
            invitesToSend: [expect.objectContaining({ target_email: 'sam@example.com', first_name: 'Sam' })],
            message: 'join us',
            inviteConfirmationText: 'send invites',
            isInviteConfirmed: true,
        })
    })

    it('clears the form only after a successful invite', async () => {
        await expectLogic(logic, () => {
            logic.actions.updateInviteAtIndex({ target_email: 'sam@example.com' }, 0)
            logic.actions.updateMessage('join us')
            logic.actions.setInviteConfirmationText('send invites')
            logic.actions.inviteTeamMembersSuccess([])
        }).toMatchValues({
            invitesToSend: [expect.objectContaining({ target_email: '' })],
            message: '',
            inviteConfirmationText: '',
            isInviteConfirmed: false,
        })
    })
})
