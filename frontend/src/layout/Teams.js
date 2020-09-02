import React from 'react'
import { useValues } from 'kea'
import { Dropdown, Menu } from 'antd'
import { userLogic } from 'scenes/userLogic'
import api from '../lib/api'

export function Teams() {
    const { user } = useValues(userLogic)
    const listItems = user.teams.map((team) => (
        <Menu.Item key={team.id}>
            <a href="" onClick={() => change(team.id)} data-attr="">
                {team.name}
            </a>
        </Menu.Item>
    ))
    const options = <Menu>{listItems}</Menu>

    async function change(id) {
        try {
            await api.update('api/user/', {
                team: {
                    current_team: id,
                },
            })
            toast.success('Team changed')
        } catch (response) {
            toast.error(response.error)
        }
    }

    return (
        <Dropdown overlay={options}>
            <div data-attr="user-options-dropdown" className="btn btn-sm btn-light" style={{ marginRight: '0.75rem' }}>
                {user.team.name}
            </div>
        </Dropdown>
    )
}
