import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { CheckCircleOutlined } from '@ant-design/icons'
import { organizationMembershipLevelToName, TeamMembershipLevel } from 'lib/constants'
import { TeamMembershipType, TeamType } from '~/types'
import { teamMembersLogicType } from './teamMembersLogicType'
import { membersLogic } from '../../organization/Settings/membersLogic'

export const teamMembersLogic = kea<teamMembersLogicType>({
    props: {} as {
        team: TeamType
    },
    key: (props) => props.team.id,
    actions: {
        changeMemberAccessLevel: (member: TeamMembershipType, level: TeamMembershipLevel) => ({
            member,
            level,
        }),
    },
    loaders: ({ values }) => ({
        explicitMembers: {
            __default: [],
            loadMembers: async () => {
                return (await api.get('api/projects/@current/explicit_members/')).results
            },
            removeMember: async (member: TeamMembershipType) => {
                await api.delete(`api/projects/@current/explicit_members/${member.user.id}/`)
                toast(
                    <div>
                        <h1 className="text-success">
                            <CheckCircleOutlined /> Removed <b>{member.user.first_name}</b> from team.
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
            (explicitMembers, organizationMembers) =>
                organizationMembers
                    .filter(({ level }) => level >= TeamMembershipLevel.Admin)
                    .concat(explicitMembers.filter(({ level }) => level < TeamMembershipLevel.Admin)),
        ],
        allMembersLoading: [
            () => [selectors.explicitMembersLoading, membersLogic.selectors.membersLoading],
            // Explicit project members joined with organization admins and owner (who get project access by default)
            (explicitMembersLoading, organizationMembersLoading) =>
                explicitMembersLoading || organizationMembersLoading,
        ],
    }),
    listeners: ({ actions }) => ({
        changeMemberAccessLevel: async ({
            member,
            level,
        }: {
            member: TeamMembershipType
            level: TeamMembershipLevel
        }) => {
            await api.update(`api/projects/@current/explicit_members/${member.user.id}/`, { level })
            toast(
                <div>
                    <h1 className="text-success">
                        <CheckCircleOutlined /> Made <b>{member.user.first_name}</b> project{' '}
                        {organizationMembershipLevelToName.get(level)}.
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
