import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { CheckCircleOutlined } from '@ant-design/icons'
import { membersLogicType } from 'types/scenes/organization/Members/logicType'
import { organizationMembershipLevelToName } from 'lib/constants'

export const membersLogic = kea<membersLogicType>({
    loaders: ({ values }) => ({
        members: {
            __default: [],
            loadMembers: async () => {
                return (await api.get('api/organizations/@current/members/')).results
            },
            changeMemberAccessLevel: async ({ member, level }) => {
                await api.update(`api/organizations/@current/members/${member.user_id}/`, { level })
                toast(
                    <div>
                        <h1 className="text-success">
                            <CheckCircleOutlined /> Made <b>{member.user_first_name}</b> organization{' '}
                            {organizationMembershipLevelToName.get(level)}.
                        </h1>
                    </div>
                )
                return values.members.map((thisMember) =>
                    thisMember.user_id === member.user_id ? { ...thisMember, level } : thisMember
                )
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
    events: ({ actions }) => ({
        afterMount: actions.loadMembers,
    }),
})
