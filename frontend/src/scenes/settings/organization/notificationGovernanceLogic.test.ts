import { organizationLogic } from 'scenes/organizationLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { notificationGovernanceLogic } from './notificationGovernanceLogic'

const MEMBERS = [
    {
        user_id: 1,
        uuid: '0198aaaa-0000-4000-8000-000000000001',
        first_name: 'Ada',
        last_name: 'Member',
        email: 'ada@example.com',
        organization_membership_level: 1,
        editable: true,
        locks: [],
    },
    {
        user_id: 2,
        uuid: '0198aaaa-0000-4000-8000-000000000002',
        first_name: 'Grace',
        last_name: 'Owner',
        email: 'grace@example.com',
        organization_membership_level: 15,
        editable: false,
        locks: [],
    },
]

describe('notificationGovernanceLogic', () => {
    let logic: ReturnType<typeof notificationGovernanceLogic.build>

    beforeEach(() => {
        useMocks({ get: { '/api/organizations/:id/notification_locks/': MEMBERS } })
        initKeaTests()
        organizationLogic.mount()
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            id: 'org-1',
            name: 'Org',
            teams: [{ id: 1, name: 'Project A' }],
        } as any)
        logic = notificationGovernanceLogic()
        logic.mount()
        logic.actions.loadMembersSuccess(MEMBERS as any)
    })

    it('stores an inverted setting the other way round', () => {
        // pipeline_notifications_disabled means "muted", so receiving the emails is a stored false.
        logic.actions.setRule('pipeline_notifications_disabled', '1', 1, 'on')
        expect(logic.values.changesToSave).toEqual([
            { user_id: 1, setting: 'pipeline_notifications_disabled', scope_id: '1', locked_value: false },
        ])

        logic.actions.setRule('pipeline_notifications_disabled', '1', 1, 'off')
        expect(logic.values.changesToSave[0].locked_value).toBe(true)
    })

    it('does not send a rule that matches what is already stored', () => {
        logic.actions.loadMembersSuccess([
            {
                ...MEMBERS[0],
                locks: [{ setting: 'discussions_mentioned', scope_id: '', locked_value: false }],
            },
            MEMBERS[1],
        ] as any)

        logic.actions.setRule('discussions_mentioned', '', 1, 'off')
        expect(logic.values.changesToSave).toEqual([])

        logic.actions.setRule('discussions_mentioned', '', 1, 'on')
        expect(logic.values.pendingChangeCount).toBe(1)
    })

    it('leaves members above your access level out of a bulk change', () => {
        const editable = MEMBERS.filter((member) => member.editable).map((member) => member.user_id)
        logic.actions.setRuleForMany('discussions_mentioned', '', editable, 'off')

        expect(logic.values.changesToSave.map((change) => change.user_id)).toEqual([1])
        expect(logic.values.affectedMemberCount).toBe(1)
    })
})
