import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { CheckCircleOutlined } from '@ant-design/icons'
import { membersLogicType } from './membersLogicType'
import { OrganizationMembershipLevel, organizationMembershipLevelToName } from 'lib/constants'
import { OrganizationMemberType } from '~/types'
import { organizationLogic } from 'scenes/organizationLogic'

export const membersLogic = kea<membersLogicType>({
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
                return (await api.get('api/organizations/@current/members/')).results
            },
            removeMember: async (member) => {
                await api.delete(`api/organizations/@current/members/${member.user_id}/`)
                toast(
                    <div>
                        <h1 className="text-success">
                            <CheckCircleOutlined /> Removed <b>{member.user_first_name}</b> from organization.
                        </h1>
                    </div>
                )
                return values.members.filter((thisMember) => thisMember.user_id !== member.user_id)
            },
        },
    }),
    listeners: ({ actions }) => ({
        changeMemberAccessLevel: async ({
            member,
            level,
        }: {
            member: OrganizationMemberType
            level: OrganizationMembershipLevel
        }) => {
            await api.update(`api/organizations/@current/members/${member.user_id}/`, { level })
            toast(
                <div>
                    <h1 className="text-success">
                        <CheckCircleOutlined /> Made <b>{member.user_first_name}</b> organization{' '}
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
