import React from 'react'
import { useValues } from 'kea'
import { Dropdown, Menu } from 'antd'
import { userLogic } from 'scenes/userLogic'

const options = (
    <Menu>
        <Menu.Item key="0">
            <a href="/logout" data-attr="user-options-logout">
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
                {user.email}
            </div>
        </Dropdown>
    )
}
