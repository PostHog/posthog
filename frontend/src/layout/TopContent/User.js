import React from 'react'
import { useActions, useValues } from 'kea'
import { Dropdown, Menu } from 'antd'
import { userLogic } from 'scenes/userLogic'

export function User() {
    const { user } = useValues(userLogic)
    const { logout } = useActions(userLogic)

    const options = (
        <Menu>
            <Menu.Item key="0">
                <a onClick={logout} data-attr="user-options-logout">
                    Logout
                </a>
            </Menu.Item>
        </Menu>
    )

    return (
        <Dropdown overlay={options}>
            <span data-attr="user-options-dropdown" className="btn btn-sm btn-light">
                {user.email}
            </span>
        </Dropdown>
    )
}
