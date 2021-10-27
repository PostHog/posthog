import React from 'react'
import { CaretDownOutlined } from '@ant-design/icons'
import { useValues } from 'kea'
import { userLogic } from '../../../scenes/userLogic'
import { ProfilePicture } from '../../../lib/components/ProfilePicture'
import { LemonPopover } from '../../../lib/components/LemonPopover'

export function AccountControl(): JSX.Element {
    const { user } = useValues(userLogic)

    return (
        <LemonPopover content={'Lorem ipsum dolor sit amet.'}>
            <div className="AccountControl__crumb">
                <ProfilePicture name={user?.first_name} email={user?.email} size="md" />
                <CaretDownOutlined />
            </div>
        </LemonPopover>
    )
}
