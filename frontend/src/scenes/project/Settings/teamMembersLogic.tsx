import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { CheckCircleOutlined } from '@ant-design/icons'
import { OrganizationMembershipLevel, TeamMembershipLevel } from 'lib/constants'
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
import { membershipLevelToName } from '../../../lib/utils/permissioning'
import { userLogic } from '../../userLogic'

const MINIMUM_DEFAULT_ACCESS_LEVEL = OrganizationMembershipLevel.Admin

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
            addMembers: async ({
                userUuids,
                level,
            }: {
                userUuids: UserBasicType['uuid'][]
                level: TeamMembershipLevel
            }) => {
                const newMembers: ExplicitTeamMemberType[] = await Promise.all(
                    userUuids.map((userUuid) =>
                        api.create(`api/projects/@current/explicit_members/`, {
                            user_uuid: userUuid,
                            level,
                        })
                    )
                )
                toast(
                    <div>
                        <h1 className="text-success">
                            <CheckCircleOutlined /> Added {newMembers.length} members{newMembers.length !== 1 && 's'} to
                            the project.
                        </h1>
                    </div>
                )
                return [...values.explicitMembers, ...newMembers]
            },
            removeMember: async (member: ExplicitTeamMemberType) => {
                await api.delete(`api/projects/@current/explicit_members/${member.user.id}/`)
                toast(
                    <div>
                        <h1 className="text-success">
                            <CheckCircleOutlined /> Removed <b>{member.user.first_name}</b> from the project.
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
                    .filter(({ level }) => level >= MINIMUM_DEFAULT_ACCESS_LEVEL)
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
                            .filter(({ parent_level }) => parent_level < MINIMUM_DEFAULT_ACCESS_LEVEL)
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
            (explicitMembersLoading, organizationMembersLoading) =>
                explicitMembersLoading || organizationMembersLoading,
        ],
        addableMembers: [
            () => [selectors.explicitMembers, membersLogic.selectors.members, userLogic.selectors.user],
            // Organization members processed to indicate if they can be added to the project or not
            (
                explicitMembers: ExplicitTeamMemberType[],
                organizationMembers: OrganizationMemberType[],
                currentUser: UserType
            ): FusedTeamMemberType[] =>
                organizationMembers
                    .filter(({ user }) => user.uuid !== currentUser.uuid)
                    .map((organizationMember) => {
                        const explicitMember = explicitMembers.find(({ user }) => user.uuid === user.uuid)
                        let effectiveLevel: OrganizationMembershipLevel | null
                        if (explicitMember) {
                            effectiveLevel = Math.max(explicitMember.effective_level, organizationMember.level)
                        } else {
                            effectiveLevel =
                                organizationMember.level >= MINIMUM_DEFAULT_ACCESS_LEVEL
                                    ? organizationMember.level
                                    : null
                        }
                        return {
                            ...organizationMember,
                            level: effectiveLevel,
                            explicit_team_level: explicitMember ? explicitMember.level : null,
                            organization_level: organizationMember.level,
                        } as FusedTeamMemberType
                    }),
        ],
    }),
    listeners: ({ actions }) => ({
        changeUserAccessLevel: async ({ user, newLevel }) => {
            await api.update(`api/projects/@current/explicit_members/${user.uuid}/`, { level: newLevel })
            toast(
                <div>
                    <h1 className="text-success">
                        <CheckCircleOutlined /> Made <b>{user.first_name}</b> project{' '}
                        {membershipLevelToName.get(newLevel)}.
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
