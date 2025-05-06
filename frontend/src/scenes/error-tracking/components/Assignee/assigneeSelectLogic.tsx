import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userGroupsLogic } from 'scenes/settings/environment/userGroupsLogic'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'
import type { OrganizationMemberType, UserGroup } from '~/types'

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

export type Assignee = UserAssignee | GroupAssignee | null

export const assigneeSelectLogic = kea<assigneeSelectLogicType>([
    path(['scenes', 'error-tracking', 'assigneeSelectLogic']),
    props({} as ErrorTrackingAssigneeSelectProps),

    connect(() => ({
        values: [
            membersLogic,
            ['meFirstMembers', 'filteredMembers', 'membersLoading'],
            userGroupsLogic,
            ['userGroups', 'filteredGroups', 'userGroupsLoading'],
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
            (s) => [s.membersLoading, s.userGroupsLoading],
            (membersLoading, userGroupsLoading): boolean => membersLoading || userGroupsLoading,
        ],

        resolveAssignee: [
            (s) => [s.userGroups, s.meFirstMembers],
            (groups, members): ((assignee: ErrorTrackingIssue['assignee']) => Assignee) => {
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
