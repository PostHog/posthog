import { expectLogic } from 'kea-test-utils'

import { inviteLogic } from '~/scenes/settings/organization/inviteLogic'
import { initKeaTests } from '~/test/init'

import { modalInterruptionTrackingLogic } from './modalInterruptionTrackingLogic'

describe('modalInterruptionTrackingLogic', () => {
    let logic: ReturnType<typeof modalInterruptionTrackingLogic.build>

    beforeEach(() => {
        sessionStorage.clear()
        initKeaTests()
        logic = modalInterruptionTrackingLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('marks the invite modal as the interrupted form when an invite is attempted with it open', async () => {
        inviteLogic.actions.showInviteModal()
        await expectLogic(logic, () => {
            inviteLogic.actions.inviteTeamMembers()
        }).toMatchValues({ interruptedForm: 'invite_members_modal' })
    })

    it('does not mark the invite modal when it is closed', async () => {
        inviteLogic.actions.hideInviteModal()
        await expectLogic(logic, () => {
            inviteLogic.actions.inviteTeamMembers()
        }).toMatchValues({ interruptedForm: null })
    })
})
