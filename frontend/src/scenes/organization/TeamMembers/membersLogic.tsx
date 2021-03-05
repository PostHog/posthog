import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { CheckCircleOutlined } from '@ant-design/icons'
import { membersLogicType } from './membersLogicType'
import { OrganizationMembershipLevel, organizationMembershipLevelToName } from 'lib/constants'
import { OrganizationMemberType } from '~/types'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

export const membersLogic = kea<membersLogicType>({
    actions: {
        changeMemberAccessLevel: (member: OrganizationMemberType, level: OrganizationMembershipLevel) => ({
            member,
            level,
        }),
        postRemoveMember: (memberId: number) => ({ memberId }),
    },
    loaders: ({ values, actions }) => ({
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
                actions.postRemoveMember(member.user_id)
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
        postRemoveMember: async ({ memberId }) => {
            if (memberId === userLogic.values.user?.id) {
                location.reload()
            }
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadMembers,
    }),
})
