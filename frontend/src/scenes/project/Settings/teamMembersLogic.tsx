import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { CheckCircleOutlined } from '@ant-design/icons'
import { OrganizationMembershipLevel, organizationMembershipLevelToName } from 'lib/constants'
import { OrganizationMemberType, TeamType } from '~/types'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamMembersLogicType } from './teamMembersLogicType'
import { membersLogic } from '../../organization/Settings/membersLogic'

export const teamMembersLogic = kea<teamMembersLogicType>({
    props: {} as {
        team: TeamType
    },
    key: (props) => props.team.id,
    actions: {
        changeMemberAccessLevel: (member: OrganizationMemberType, level: OrganizationMembershipLevel) => ({
            member,
            level,
        }),
    },
    loaders: ({ values }) => ({
        members: {
            __default: [],
            loadMembers: async () => {
                return (await api.get('api/projects/@current/explicit_members/')).results
            },
            removeMember: async (member: OrganizationMemberType) => {
                await api.delete(`api/projects/@current/explicit_members/${member.user.id}/`)
                toast(
                    <div>
                        <h1 className="text-success">
                            <CheckCircleOutlined /> Removed <b>{member.user.first_name}</b> from team.
                        </h1>
                    </div>
                )
                return values.members.filter((thisMember) => thisMember.user.id !== member.user.id)
            },
        },
    }),
    selectors: ({ selectors }) => ({
        relevantMembers: [
            () => [selectors.members, membersLogic.selectors.members],
            // Organization admins and owner (who get project acess by default) + explicit project members
            (explicitTeamMembers, organizationMembers) =>
                organizationMembers
                    .filter(({ level }) => level >= OrganizationMembershipLevel.Admin)
                    .concat(explicitTeamMembers.filter(({ level }) => level < OrganizationMembershipLevel.Admin)),
        ],
    }),
    listeners: ({ actions }) => ({
        changeMemberAccessLevel: async ({
            member,
            level,
        }: {
            member: OrganizationMemberType
            level: OrganizationMembershipLevel
        }) => {
            await api.update(`api/organizations/@current/members/${member.user.id}/`, { level })
            toast(
                <div>
                    <h1 className="text-success">
                        <CheckCircleOutlined /> Made <b>{member.user.first_name}</b> organization{' '}
                        {organizationMembershipLevelToName.get(level)}.
                    </h1>
                </div>
            )
            // reload organization to account for no longer being organization owner
            if (level === OrganizationMembershipLevel.Owner) {
                organizationLogic.actions.loadCurrentOrganization()
            }
            actions.loadMembers()
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadMembers,
    }),
})
