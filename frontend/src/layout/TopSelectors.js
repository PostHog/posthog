import React from 'react'
import { useValues, useActions } from 'kea'
import { Dropdown, Menu } from 'antd'
import { userLogic } from 'scenes/userLogic'
import { red } from '@ant-design/colors'

const options = (
    <Menu>
        <Menu.Item key="0">
            <a href="/logout" data-attr="user-options-logout" style={{ color: red.primary }}>
                Logout
            </a>
        </Menu.Item>
    </Menu>
)

export function User() {
    const { user } = useValues(userLogic)

    return (
        <Dropdown overlay={options}>
            <div data-attr="user-options-dropdown" className="btn btn-sm btn-light">
                Me: <b>{user.email}</b>
            </div>
        </Dropdown>
    )
}

export function Organization() {
    const { user } = useValues(userLogic)
    const { userUpdateRequest } = useActions(userLogic)

    return (
        <Dropdown
            overlay={
                <Menu>
                    {user.organizations.map((organization) => (
                        <Menu.Item key={organization.id}>
                            <a
                                href=""
                                onClick={() =>
                                    userUpdateRequest({ user: { current_organization_id: organization.id } })
                                }
                                data-attr=""
                            >
                                {organization.id === user.current_organization_id ? (
                                    organization.name
                                ) : (
                                    <b>→ {organization.name}</b>
                                )}
                            </a>
                        </Menu.Item>
                    ))}
                </Menu>
            }
        >
            <div data-attr="user-options-dropdown" className="btn btn-sm btn-light" style={{ marginRight: '0.75rem' }}>
                Organization: <b>{user.organization.name}</b>
            </div>
        </Dropdown>
    )
}

export function Projects() {
    const { user } = useValues(userLogic)
    const { userUpdateRequest } = useActions(userLogic)

    return (
        <Dropdown
            overlay={
                <Menu>
                    {user.organization.teams.map((team) => (
                        <Menu.Item key={team.id}>
                            <a
                                href=""
                                onClick={() => userUpdateRequest({ user: { current_team_id: team.id } })}
                                data-attr=""
                            >
                                {team.id === user.current_team_id ? team.name : <b>→ {team.name}</b>}
                            </a>
                        </Menu.Item>
                    ))}
                </Menu>
            }
        >
            <div data-attr="user-options-dropdown" className="btn btn-sm btn-light" style={{ marginRight: '0.75rem' }}>
                Project: <b>{user.team.name}</b>
            </div>
        </Dropdown>
    )
}
