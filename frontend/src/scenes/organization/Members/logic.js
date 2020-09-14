import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { CheckCircleOutlined } from '@ant-design/icons'

export const membersLogic = kea({
    loaders: ({ actions }) => ({
        members: {
            __default: [],
            loadMembers: async () => {
                return await api.get('api/organization/members/')
            },
            removeMember: async (member) => {
                const result = await api.delete(`api/organization/members/${member.user_id}/`)
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
