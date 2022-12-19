import { useValues } from 'kea'
import { Divider } from 'antd'
import { useAnchor } from 'lib/hooks/useAnchor'
import { router } from 'kea-router'
import { UpdateEmailPreferences } from './UpdateEmailPreferences'
import { ChangePassword } from './ChangePassword'
import { PersonalAPIKeys } from 'lib/components/PersonalAPIKeys'
import { OptOutCapture } from './OptOutCapture'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { UserDetails } from './UserDetails'

export const scene: SceneExport = {
    component: MySettings,
}

export function MySettings(): JSX.Element {
    const { location } = useValues(router)

    useAnchor(location.hash)

    return (
        <>
            <PageHeader title="My settings" />
            <div className="border rounded p-6 mt-4">
                <UserDetails />
                <Divider />

                <h2 id="password" className="subtitle">
                    Change Password
                </h2>
                <ChangePassword />
                <Divider />
                <h2 id="personal-api-keys" className="subtitle">
                    Personal API Keys
                </h2>
                <PersonalAPIKeys />
                <Divider />
                <div id="notifications">
                    <h2 className="subtitle">Notifications</h2>
                    <UpdateEmailPreferences />
                </div>
                <Divider />
                <h2 id="optout" className="subtitle">
                    Anonymize Data Collection
                </h2>
                <OptOutCapture />
            </div>
        </>
    )
}
