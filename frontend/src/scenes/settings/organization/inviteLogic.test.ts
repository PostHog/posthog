import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { inviteLogic } from './inviteLogic'

describe('inviteLogic', () => {
    let logic: ReturnType<typeof inviteLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = inviteLogic()
        logic.mount()
    })

    it('gives every invite row a distinct stable id', async () => {
        logic.actions.appendInviteRow()
        logic.actions.appendInviteRow()

        await expectLogic(logic).toMatchValues({
            invitesToSend: expect.arrayContaining([expect.objectContaining({ id: expect.any(String) })]),
        })

        const ids = logic.values.invitesToSend.map((invite) => invite.id)
        expect(ids).toHaveLength(3)
        expect(new Set(ids).size).toBe(3)
    })

    it('keeps the surviving rows and their ids when a middle row is deleted', async () => {
        logic.actions.appendInviteRow()
        logic.actions.appendInviteRow()
        logic.actions.updateInviteAtIndex({ target_email: 'first@example.com' }, 0)
        logic.actions.updateInviteAtIndex({ target_email: 'middle@example.com' }, 1)
        logic.actions.updateInviteAtIndex({ target_email: 'last@example.com' }, 2)

        const [first, , last] = logic.values.invitesToSend

        logic.actions.deleteInviteAtIndex(1)

        expect(logic.values.invitesToSend).toEqual([first, last])
    })
})
