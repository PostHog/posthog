import React from 'react'
import { useValues } from 'kea'
import { Dropdown } from 'lib/components/Dropdown'
import { userLogic } from 'scenes/userLogic'

export function User() {
    const { user } = useValues(userLogic)

    return (
        <span>
            <Dropdown title={user.email} buttonClassName="btn btn-sm btn-light">
                <a className={'dropdown-item'} href="/logout">
                    Logout
                </a>
            </Dropdown>
        </span>
    )
}
