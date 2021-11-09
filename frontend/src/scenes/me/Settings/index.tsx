import React from 'react'
import { useValues } from 'kea'
import { Divider, Card } from 'antd'
import { useAnchor } from 'lib/hooks/useAnchor'
import { router } from 'kea-router'
import { UpdateEmailPreferences } from './UpdateEmailPreferences'
import { ChangePassword } from './ChangePassword'
import { PersonalAPIKeys } from 'lib/components/PersonalAPIKeys'
import { OptOutCapture } from './OptOutCapture'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: MySettings,
}

export function MySettings(): JSX.Element {
    const { location } = useValues(router)

    useAnchor(location.hash)

    return (
        <div style={{ marginBottom: 128 }}>
            <PageHeader title="My Settings" />
            <Card>
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
                <h2 className="subtitle">Security and Feature Updates</h2>
                <UpdateEmailPreferences />
                <Divider />
                <h2 id="optout" className="subtitle">
                    Anonymize Data Collection
                </h2>
                <OptOutCapture />
            </Card>
        </div>
    )
}
