import React from 'react'
import { useValues, useActions } from 'kea'
import { Dropdown, Menu } from 'antd'
import { userLogic } from 'scenes/userLogic'

export function Teams() {
    const { user } = useValues(userLogic)
    const { userUpdateRequest } = useActions(userLogic)

    return (
        <Dropdown
            overlay={
                <Menu>
                    {user.teams.map((team) => (
                        <Menu.Item key={team.id}>
                            <a
                                href=""
                                onClick={() => userUpdateRequest({ user: { current_team_id: team.id } })}
                                data-attr=""
                            >
                                {team.name}
                            </a>
                        </Menu.Item>
                    ))}
                </Menu>
            }
        >
            <div data-attr="user-options-dropdown" className="btn btn-sm btn-light" style={{ marginRight: '0.75rem' }}>
                {user.team.name}
            </div>
        </Dropdown>
    )
}
