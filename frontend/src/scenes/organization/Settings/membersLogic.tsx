import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { CheckCircleOutlined } from '@ant-design/icons'
import { membersLogicType } from './membersLogicType'
import { OrganizationMembershipLevel } from 'lib/constants'
import { OrganizationMemberType } from '~/types'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'
import { membershipLevelToName } from '../../../lib/utils/permissioning'

export const membersLogic = kea<membersLogicType>({
    actions: {
        changeMemberAccessLevel: (member: OrganizationMemberType, level: OrganizationMembershipLevel) => ({
            member,
            level,
        }),
        postRemoveMember: (userUuid: string) => ({ userUuid }),
    },
    loaders: ({ values, actions }) => ({
        members: {
            __default: [] as OrganizationMemberType[],
            loadMembers: async () => {
                return (await api.get('api/organizations/@current/members/?limit=200')).results
            },
            removeMember: async (member: OrganizationMemberType) => {
                await api.delete(`api/organizations/@current/members/${member.user.uuid}/`)
                toast(
                    <div>
                        <h1 className="text-success">
                            <CheckCircleOutlined /> Removed <b>{member.user.first_name}</b> from organization.
                        </h1>
                    </div>
                )
                actions.postRemoveMember(member.user.uuid)
                return values.members.filter((thisMember) => thisMember.user.id !== member.user.id)
            },
        },
    }),
    listeners: ({ actions }) => ({
        changeMemberAccessLevel: async ({ member, level }) => {
            await api.update(`api/organizations/@current/members/${member.user.uuid}/`, { level })
            toast(
                <div>
                    <h1 className="text-success">
                        <CheckCircleOutlined /> Made <b>{member.user.first_name}</b> organization{' '}
                        {membershipLevelToName.get(level)}.
                    </h1>
                </div>
            )
            // reload organization to account for no longer being organization owner
            if (level === OrganizationMembershipLevel.Owner) {
                organizationLogic.actions.loadCurrentOrganization()
            }
            actions.loadMembers()
        },
        postRemoveMember: async ({ userUuid }) => {
            if (userUuid === userLogic.values.user?.uuid) {
                location.reload()
            }
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadMembers,
    }),
})
