import React from 'react'
import { CaretDownOutlined } from '@ant-design/icons'
import { useValues } from 'kea'
import { userLogic } from '../../../scenes/userLogic'
import { ProfilePicture } from '../../../lib/components/ProfilePicture'
import { LemonPopover } from '../../../lib/components/LemonPopover'

export function AccountControl(): JSX.Element {
    const { user } = useValues(userLogic)

    return (
        <LemonPopover
            overlayStyle={{ width: '20rem' }}
            content={
                <>
                    <div className="AccountControl__section">
                        <h5 className="l5">Signed in as</h5>
                    </div>
                    <div className="AccountControl__section">
                        <h5 className="l5">Current organization</h5>
                    </div>
                    <div className="AccountControl__section">
                        <h5 className="l5">Other organizations</h5>
                    </div>
                    <div className="AccountControl__section">
                        <h5 className="l5">PostHog status</h5>
                    </div>
                </>
            }
        >
            <div className="AccountControl__crumb">
                <ProfilePicture name={user?.first_name} email={user?.email} size="md" />
                <CaretDownOutlined />
            </div>
        </LemonPopover>
    )
}
