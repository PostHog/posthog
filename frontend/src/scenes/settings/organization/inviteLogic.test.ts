import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { inviteLogic } from './inviteLogic'

const INVITE_DRAFT_STORAGE_KEY = 'posthog_invite_draft'

const EMPTY_ROW = {
    target_email: '',
    first_name: '',
    level: 1,
    isValid: true,
    private_project_access: [],
}

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

    it('discards the persisted draft when invites are reset, as Cancel does', async () => {
        await expectLogic(logic, () => {
            logic.actions.updateInviteAtIndex({ target_email: 'contractor@example.com' }, 0)
            logic.actions.updateMessage('join us')
            logic.actions.setInviteConfirmationText('send invites')
            logic.actions.resetInvites()
        }).toFinishAllListeners()

        logic.unmount()
        logic = inviteLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({
            invitesToSend: [expect.objectContaining({ target_email: '' })],
            message: '',
            inviteConfirmationText: '',
        })
    })

    it('does not restore a draft left by a different organization', async () => {
        sessionStorage.setItem(
            INVITE_DRAFT_STORAGE_KEY,
            JSON.stringify({
                userUuid: 'someone-else',
                organizationId: 'another-org',
                invitesToSend: [{ ...EMPTY_ROW, target_email: 'stale@example.com' }],
                message: 'from another org',
                inviteConfirmationText: '',
            })
        )

        logic.unmount()
        logic = inviteLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({
            invitesToSend: [expect.objectContaining({ target_email: '' })],
            message: '',
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
