import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { CheckCircleOutlined } from '@ant-design/icons'

export const teamLogic = kea({
    loaders: ({ actions }) => ({
        users: {
            __default: {},
            loadUsers: async () => {
                return await api.get('api/team/user/')
            },
            deleteUser: async (user) => {
                const result = await api.delete(`api/team/user/${user.distinct_id}/`)
                actions.loadUsers()
                toast(
                    <div>
                        <h1 className="text-success">
                            <CheckCircleOutlined /> User <b>{user.first_name}</b> was successfully deleted!
                        </h1>
                    </div>
                )
                return result
            },
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadUsers,
    }),
})
