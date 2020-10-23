import React from 'react'
import { useValues } from 'kea'
import { Divider } from 'antd'
import { useAnchor } from 'lib/hooks/useAnchor'
import { router } from 'kea-router'
import { hot } from 'react-hot-loader/root'
import { UpdateEmailPreferences } from './UpdateEmailPreferences'
import { ChangePassword } from './ChangePassword'
import { PersonalAPIKeys } from 'lib/components/PersonalAPIKeys'
import { OptOutCapture } from './OptOutCapture'
import { userLogic } from 'scenes/userLogic'

export const MySettings = hot(_MySettings)
function _MySettings(): JSX.Element {
    const { location } = useValues(router)
    const { user } = useValues(userLogic)

    useAnchor(location.hash)

    return (
        <div>
            <h1 className="page-header">My Settings – {user?.name}</h1>
            <Divider />
            <h2 id="password">Change Password</h2>
            <ChangePassword />
            <Divider />
            <h2 id="personal-api-keys">Personal API Keys</h2>
            <PersonalAPIKeys />
            <Divider />
            <h2>Security and Feature Updates</h2>
            <UpdateEmailPreferences />
            <Divider />
            <h2 id="optout">Anonymize Data Collection</h2>
            <OptOutCapture />
        </div>
    )
}
