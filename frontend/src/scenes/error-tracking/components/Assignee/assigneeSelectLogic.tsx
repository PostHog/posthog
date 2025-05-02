import Fuse from 'fuse.js'
import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userGroupsLogic } from 'scenes/settings/environment/userGroupsLogic'
import { rolesLogic } from 'scenes/settings/organization/Permissions/Roles/rolesLogic'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'
import type { OrganizationMemberType, RoleType, UserGroup } from '~/types'

import type { assigneeSelectLogicType } from './assigneeSelectLogicType'

export type ErrorTrackingAssigneeSelectProps = {
    assignee: ErrorTrackingIssue['assignee']
}

export type UserAssignee = {
    id: number
    type: 'user'
    user: OrganizationMemberType['user']
}

export type GroupAssignee = {
    id: string
    type: 'group'
    group: UserGroup
}

export type RoleAssignee = {
    id: string
    type: 'role'
    role: RoleType
}

export type Assignee = UserAssignee | GroupAssignee | RoleAssignee | null

export interface RolesFuse extends Fuse<RoleType> {}

export const assigneeSelectLogic = kea<assigneeSelectLogicType>([
    path(['scenes', 'error-tracking', 'assigneeSelectLogic']),
    props({} as ErrorTrackingAssigneeSelectProps),

    connect(() => ({
        values: [
            membersLogic,
            ['meFirstMembers', 'filteredMembers', 'membersLoading'],
            userGroupsLogic,
            ['userGroups', 'filteredGroups', 'userGroupsLoading'],
            rolesLogic,
            ['roles', 'rolesLoading'],
        ],
        actions: [
            membersLogic,
            ['setSearch as setMembersSearch', 'ensureAllMembersLoaded'],
            userGroupsLogic,
            ['setSearch as setGroupsSearch', 'ensureAllGroupsLoaded'],
        ],
    })),

    actions({
        ensureAssigneeTypesLoaded: true,
        setSearch: (search) => ({ search }),
    }),

    reducers({
        search: ['', { setSearch: (_, { search }) => search }],
    }),

    listeners(({ values, actions }) => ({
        setSearch: () => {
            actions.setGroupsSearch(values.search)
            actions.setMembersSearch(values.search)
        },
        ensureAssigneeTypesLoaded: () => {
            actions.ensureAllGroupsLoaded()
            actions.ensureAllMembersLoaded()
        },
    })),

    selectors({
        loading: [
            (s) => [s.membersLoading, s.userGroupsLoading, s.rolesLoading],
            (membersLoading, userGroupsLoading, rolesLoading): boolean =>
                membersLoading || userGroupsLoading || rolesLoading,
        ],

        rolesFuse: [
            (s) => [s.roles],
            (roles): RolesFuse => new Fuse<RoleType>(roles, { keys: ['name'], threshold: 0.3 }),
        ],
        filteredRoles: [
            (s) => [s.roles, s.rolesFuse, s.search],
            (roles, rolesFuse, search): RoleType[] =>
                search ? rolesFuse.search(search).map((result) => result.item) : roles ?? [],
        ],

        resolveAssignee: [
            (s) => [s.userGroups, s.roles, s.meFirstMembers],
            (groups, roles, members): ((assignee: ErrorTrackingIssue['assignee']) => Assignee) => {
                return (assignee: ErrorTrackingIssue['assignee']) => {
                    if (assignee) {
                        if (assignee.type === 'user_group') {
                            const assignedGroup = groups.find((group) => group.id === assignee.id)
                            return assignedGroup
                                ? {
                                      id: assignedGroup.id,
                                      type: 'group',
                                      group: assignedGroup,
                                  }
                                : null
                        } else if (assignee.type === 'role') {
                            const assignedRole = roles.find((role) => role.id === assignee.id)
                            return assignedRole
                                ? {
                                      id: assignedRole.id,
                                      type: 'role',
                                      role: assignedRole,
                                  }
                                : null
                        }

                        const assignedMember = members.find((member) => member.user.id === assignee.id)
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
