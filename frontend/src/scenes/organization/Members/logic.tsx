import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { CheckCircleOutlined } from '@ant-design/icons'
import { membersLogicType } from 'types/scenes/organization/Members/logicType'

export const membersLogic = kea<membersLogicType>({
    loaders: ({ actions }) => ({
        members: {
            __default: [],
            loadMembers: async () => {
                return (await api.get('api/organizations/@current/members/')).results
            },
            removeMember: async (member) => {
                const result = await api.delete(`api/organizations/@current/members/${member.user_id}/`)
                actions.loadMembers()
                toast(
                    <div>
                        <h1 className="text-success">
                            <CheckCircleOutlined /> Removed <b>{member.user_first_name}</b> from organization.
                        </h1>
                    </div>
                )
                return result
            },
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadMembers,
    }),
})
