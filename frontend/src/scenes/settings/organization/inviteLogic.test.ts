import { expectLogic } from 'kea-test-utils'

import { OrganizationMembershipLevel } from 'lib/constants'

import { initKeaTests } from '~/test/init'

import { inviteLogic } from './inviteLogic'

describe('inviteLogic', () => {
    let logic: ReturnType<typeof inviteLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = inviteLogic()
        logic.mount()
    })

    const selectOwnerInvite = (): void => {
        logic.actions.updateInviteAtIndex(
            { target_email: 'new-owner@posthog.com', level: OrganizationMembershipLevel.Owner },
            0
        )
    }

    it.each([
        ['send invites', true],
        ['send invites ', true],
        ['  Send Invites  ', true],
        ['send invite', false],
        ['', false],
    ])('treats owner confirmation %p as confirmed=%p', async (text, expected) => {
        selectOwnerInvite()
        logic.actions.setInviteConfirmationText(text)
        await expectLogic(logic).toMatchValues({ isInviteConfirmed: expected, canSubmit: expected })
    })

    it('drops the owner confirmation when the invite rows are reset', async () => {
        selectOwnerInvite()
        logic.actions.setInviteConfirmationText('send invites')
        await expectLogic(logic).toMatchValues({ canSubmit: true })

        logic.actions.resetInviteRows()
        selectOwnerInvite()

        await expectLogic(logic).toMatchValues({
            isInviteConfirmed: false,
            submitDisabledReason: 'Type "send invites" to confirm owner-level invites',
        })
    })

    it('names the invalid email rather than the owner confirmation as the blocker', async () => {
        logic.actions.updateInviteAtIndex({ target_email: 'not-an-email', isValid: false }, 0)
        await expectLogic(logic).toMatchValues({ submitDisabledReason: 'Fix the invalid email addresses above' })
    })
})
