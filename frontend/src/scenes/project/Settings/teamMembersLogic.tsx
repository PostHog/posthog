import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { CheckCircleOutlined } from '@ant-design/icons'
import { OrganizationMembershipLevel, organizationMembershipLevelToName, TeamMembershipLevel } from 'lib/constants'
import {
    ExplicitTeamMemberType,
    FusedTeamMemberType,
    OrganizationMemberType,
    TeamType,
    UserBasicType,
    UserType,
} from '~/types'
import { teamMembersLogicType } from './teamMembersLogicType'
import { membersLogic } from '../../organization/Settings/membersLogic'

export const teamMembersLogic = kea<teamMembersLogicType>({
    props: {} as {
        team: TeamType
    },
    key: (props) => props.team.id,
    actions: {
        changeUserAccessLevel: (user: UserBasicType, newLevel: TeamMembershipLevel) => ({
            user,
            newLevel,
        }),
    },
    loaders: ({ values }) => ({
        explicitMembers: {
            __default: [] as ExplicitTeamMemberType[],
            loadMembers: async () => {
                return await api.get('api/projects/@current/explicit_members/')
            },
            addMember: async (user: UserType) => {
                const newMember: ExplicitTeamMemberType = await api.create(`api/projects/@current/explicit_members/`, {
                    user_id: user.id,
                })
                toast(
                    <div>
                        <h1 className="text-success">
                            <CheckCircleOutlined /> Removed <b>{user.first_name}</b> from project.
                        </h1>
                    </div>
                )
                return [...values.explicitMembers, newMember]
            },
            removeMember: async (member: ExplicitTeamMemberType) => {
                await api.delete(`api/projects/@current/explicit_members/${member.user.id}/`)
                toast(
                    <div>
                        <h1 className="text-success">
                            <CheckCircleOutlined /> Removed <b>{member.user.first_name}</b> from project.
                        </h1>
                    </div>
                )
                return values.explicitMembers.filter((thisMember) => thisMember.user.id !== member.user.id)
            },
        },
    }),
    selectors: ({ selectors }) => ({
        allMembers: [
            () => [selectors.explicitMembers, membersLogic.selectors.members],
            // Explicit project members joined with organization admins and owner (who get project access by default)
            (
                explicitMembers: ExplicitTeamMemberType[],
                organizationMembers: OrganizationMemberType[]
            ): FusedTeamMemberType[] =>
                organizationMembers
                    .filter(({ level }) => level >= OrganizationMembershipLevel.Admin)
                    .map(
                        (member) =>
                            ({
                                ...member,
                                explicit_team_level: null,
                                organization_level: member.level,
                            } as FusedTeamMemberType)
                    )
                    .concat(
                        explicitMembers
                            .filter(({ parent_level }) => parent_level < OrganizationMembershipLevel.Admin)
                            .map(
                                (member) =>
                                    ({
                                        ...member,
                                        level: member.effective_level,
                                        explicit_team_level: member.level,
                                        organization_level: member.parent_level,
                                    } as FusedTeamMemberType)
                            )
                    ),
        ],
        allMembersLoading: [
            () => [selectors.explicitMembersLoading, membersLogic.selectors.membersLoading],
            // Explicit project members joined with organization admins and owner (who get project access by default)
            (explicitMembersLoading, organizationMembersLoading) =>
                explicitMembersLoading || organizationMembersLoading,
        ],
    }),
    listeners: ({ actions }) => ({
        changeUserAccessLevel: async ({ user, newLevel }) => {
            await api.update(`api/projects/@current/explicit_members/${user.uuid}/`, { level: newLevel })
            toast(
                <div>
                    <h1 className="text-success">
                        <CheckCircleOutlined /> Made <b>{user.first_name}</b> project{' '}
                        {organizationMembershipLevelToName.get(newLevel)}.
                    </h1>
                </div>
            )
            actions.loadMembers()
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadMembers,
    }),
})
