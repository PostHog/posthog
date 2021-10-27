import React from 'react'
import { CaretDownOutlined } from '@ant-design/icons'
import { useValues } from 'kea'
import { userLogic } from '../../../scenes/userLogic'
import { ProfilePicture } from '../../../lib/components/ProfilePicture'

export function AccountControl(): JSX.Element {
    const { user } = useValues(userLogic)

    return (
        <div className="AccountControl__crumb">
            <ProfilePicture name={user?.first_name} email={user?.email} size="md" />
            <CaretDownOutlined />
        </div>
    )
}
