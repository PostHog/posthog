import { IconPerson } from '@posthog/icons'
import { Lettermark, ProfilePicture } from '@posthog/lemon-ui'
import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { fullName } from 'lib/utils'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userGroupsLogic } from 'scenes/settings/environment/userGroupsLogic'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'
import { OrganizationMemberType, UserGroup } from '~/types'

import type { assigneeSelectLogicType } from './assigneeSelectLogicType'

export type ErrorTrackingAssigneeSelectProps = {
    assignee: ErrorTrackingIssue['assignee']
}

export type AssigneeDisplayType = { id: string | number; icon: JSX.Element; displayName?: string }

const groupDisplay = (group: UserGroup, index: number): AssigneeDisplayType => ({
    id: group.id,
    displayName: group.name,
    icon: <Lettermark name={group.name} index={index} rounded />,
})

const userDisplay = (member: OrganizationMemberType): AssigneeDisplayType => ({
    id: member.user.id,
    displayName: fullName(member.user),
    icon: <ProfilePicture size="md" user={member.user} />,
})

const unassignedDisplay: AssigneeDisplayType = {
    id: 'unassigned',
    displayName: 'Unassigned',
    icon: <IconPerson className="rounded-full border border-dashed border-muted text-secondary p-0.5" />,
}

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

        groupOptions: [(s) => [s.filteredGroups], (groups): AssigneeDisplayType[] => groups.map(groupDisplay)],
        memberOptions: [(s) => [s.filteredMembers], (members): AssigneeDisplayType[] => members.map(userDisplay)],

        computeAssignee: [
            (s) => [s.userGroups, s.meFirstMembers],
            (groups, members): ((assignee: ErrorTrackingIssue['assignee']) => AssigneeDisplayType) => {
                return (assignee: ErrorTrackingIssue['assignee']) => {
                    if (assignee) {
                        if (assignee.type === 'user_group') {
                            const assignedGroup = groups.find((group) => group.id === assignee.id)
                            return assignedGroup ? groupDisplay(assignedGroup, 0) : unassignedDisplay
                        }

                        const assignedMember = members.find((member) => member.user.id === assignee.id)
                        return assignedMember ? userDisplay(assignedMember) : unassignedDisplay
                    }

                    return unassignedDisplay
                }
            },
        ],
    }),
])
