import Fuse from 'fuse.js'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { membersLogic } from 'scenes/organization/membersLogic'
import { rolesLogic } from 'scenes/settings/organization/Permissions/Roles/rolesLogic'

import type { RoleType } from '~/types'

import type { assigneeSelectLogicType } from './assigneeSelectLogicType'
import { Assignee, TicketAssignee } from './types'

export interface RolesFuse extends Fuse<RoleType> {}

export const assigneeSelectLogic = kea<assigneeSelectLogicType>([
    path(['products', 'conversations', 'frontend', 'components', 'Assignee', 'assigneeSelectLogic']),
    connect(() => ({
        values: [
            membersLogic,
            ['meFirstMembers', 'filteredMembers', 'membersLoading'],
            rolesLogic,
            ['roles', 'rolesLoading'],
        ],
        actions: [membersLogic, ['setSearch as setMembersSearch', 'ensureAllMembersLoaded']],
    })),
    actions({
        ensureAssigneeTypesLoaded: true,
        setSearch: (search: string) => ({ search }),
    }),
    reducers({
        search: ['', { setSearch: (_, { search }) => search }],
    }),
    listeners(({ values, actions }) => ({
        setSearch: () => {
            actions.setMembersSearch(values.search)
        },
        ensureAssigneeTypesLoaded: () => {
            actions.ensureAllMembersLoaded()
        },
    })),
    selectors({
        loading: [
            (s) => [s.membersLoading, s.rolesLoading],
            (membersLoading, rolesLoading): boolean => membersLoading || rolesLoading,
        ],

        rolesFuse: [
            (s) => [s.roles],
            (roles): RolesFuse => new Fuse<RoleType>(roles, { keys: ['name'], threshold: 0.3 }),
        ],

        filteredRoles: [
            (s) => [s.roles, s.rolesFuse, s.search],
            (roles, rolesFuse, search): RoleType[] =>
                search ? rolesFuse.search(search).map((result) => result.item) : (roles ?? []),
        ],
        resolveAssignee: [
            (s) => [s.roles, s.meFirstMembers],
            (roles, members): ((assignee: TicketAssignee) => Assignee) => {
                return (assignee: TicketAssignee) => {
                    if (assignee) {
                        if (assignee.type === 'role') {
                            const assignedRole = roles.find((role) => String(role.id) === String(assignee.id))
                            return assignedRole
                                ? {
                                      id: assignedRole.id,
                                      type: 'role',
                                      role: assignedRole,
                                  }
                                : null
                        }

                        const assignedMember = members.find((member) => String(member.user.id) === String(assignee.id))
                        return assignedMember
                            ? {
                                  id: assignedMember.user.id,
                                  type: 'user',
                                  user: assignedMember.user,
                              }
                            : null
                    }

                    return null
                }
            },
        ],
    }),
])
