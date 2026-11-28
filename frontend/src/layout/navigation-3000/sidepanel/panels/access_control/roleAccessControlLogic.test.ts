import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { RoleType } from '~/types'

import { roleAccessControlLogic } from './roleAccessControlLogic'

describe('roleAccessControlLogic', () => {
    let logic: ReturnType<typeof roleAccessControlLogic.build>

    beforeEach(() => {
        initKeaTests()
        router.actions.push(urls.settings('organization-roles'), {}, { role: 'role-a' })
        logic = roleAccessControlLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('syncs the selected role with the role in the URL hash', async () => {
        await expectLogic(logic).toMatchValues({ selectedRoleId: 'role-a' })

        router.actions.push(urls.settings('organization-roles'), {}, { role: 'role-b' })
        await expectLogic(logic).toMatchValues({ selectedRoleId: 'role-b' })

        router.actions.push(urls.settings('organization-roles'))
        await expectLogic(logic).toMatchValues({ selectedRoleId: null })
    })

    it('adds, removes and creates roles to match the member roles it is given', async () => {
        const role = (id: string, memberUuids: string[]): RoleType =>
            ({
                id,
                name: id,
                members: memberUuids.map((uuid) => ({ id: `${id}-${uuid}`, user: { uuid } })),
            }) as unknown as RoleType
        useMocks({
            post: {
                '/api/organizations/:org/roles/': { id: 'brand-new', name: 'brand new', members: [] },
                '/api/organizations/:org/roles/:role/role_memberships/': { id: 'membership', user: { uuid: 'u1' } },
            },
            delete: { '/api/organizations/:org/roles/:role/role_memberships/:membership/': [204] },
        })
        logic.actions.loadRolesSuccess([role('kept', ['u1']), role('dropped', ['u1']), role('joined', [])])

        await expectLogic(logic, () => {
            logic.actions.setMemberRoles('u1', ['kept', 'joined'], ['brand new'])
        }).toDispatchActionsInAnyOrder([
            (action) =>
                action.type === logic.actionTypes.addMembersToRole &&
                action.payload.role.id === 'joined' &&
                action.payload.members[0] === 'u1',
            (action) =>
                action.type === logic.actionTypes.removeMemberFromRole &&
                action.payload.role.id === 'dropped' &&
                action.payload.roleMemberId === 'dropped-u1',
            logic.actionCreators.createRoleWithMember('brand new', 'u1'),
        ])
        await expectLogic(logic).toFinishAllListeners()
    })
})
