import { MOCK_DEFAULT_ORGANIZATION, MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { OrganizationMembershipLevel } from 'lib/constants'
import { membersLogic } from 'scenes/organization/membersLogic'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { inviteLogic } from './inviteLogic'

describe('inviteLogic', () => {
    let logic: ReturnType<typeof inviteLogic.build>

    beforeEach(async () => {
        initKeaTests(true, undefined, undefined, MOCK_DEFAULT_ORGANIZATION)
        logic = inviteLogic()
        logic.mount()
        logic.actions.ensureAllMembersLoaded()
        await expectLogic(membersLogic).toDispatchActions(['loadAllMembersSuccess'])
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([
        ['the current user', 'john.doe@posthog.com', true],
        ['another member, in any letter case', ' Rose.Dawson@PostHog.com', true],
        ['a new person', 'new.person@example.com', false],
    ])('marks an invite row for %s', async (_description, email, isExistingMember) => {
        logic.actions.updateInviteAtIndex({ target_email: email, isValid: true }, 0)

        await expectLogic(logic).toMatchValues({
            existingMemberInviteRows: [isExistingMember],
            canSubmit: !isExistingMember,
        })
    })

    it('sends a guest invite with the current project and its grants', async () => {
        const create = jest.spyOn(api, 'create').mockResolvedValue([])
        logic.actions.updateInviteAtIndex(
            {
                target_email: 'guest@example.com',
                level: OrganizationMembershipLevel.Guest,
                isValid: true,
                guest_grants: [{ resource: 'dashboard', id: '12' }],
            },
            0
        )
        await expectLogic(logic, () => logic.actions.inviteTeamMembers()).toFinishAllListeners()
        expect(create).toHaveBeenCalledWith(expect.stringContaining('/invites/bulk/'), [
            expect.objectContaining({
                level: OrganizationMembershipLevel.Guest,
                private_project_access: [{ id: MOCK_TEAM_ID, level: AccessControlLevel.Member }],
                guest_grants: [{ resource: 'dashboard', id: '12' }],
            }),
        ])
    })

    it('shows a message validation error under the field until the message changes', async () => {
        logic.actions.inviteTeamMembersFailure('', {
            status: 400,
            attr: 'message',
            code: 'invalid_url',
            detail: 'URLs are not allowed in this field.',
        })
        await expectLogic(logic).toMatchValues({ messageError: 'URLs are not allowed in this field.' })

        logic.actions.updateInviteAtIndex({ first_name: 'Jo' }, 0)
        await expectLogic(logic).toMatchValues({ messageError: 'URLs are not allowed in this field.' })

        logic.actions.updateMessage('no link this time')
        await expectLogic(logic).toMatchValues({ messageError: null })
    })
})
