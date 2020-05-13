import React, { useEffect, useState } from 'react'
import { useValues } from 'kea'
import api from './../lib/api'
import { Button } from 'antd'
import { ChangelogModal } from '~/layout/ChangelogModal'
import { userLogic } from 'scenes/userLogic'

export function LatestVersion() {
    const { user } = useValues(userLogic)
    const [latestVersion, setLatestVersion] = useState(null)
    const [changelogOpen, setChangelogOpen] = useState(false)

    useEffect(() => {
        api.get('https://update.posthog.com/versions').then(versions => {
            setLatestVersion(versions[0]['version'])
        })
    }, [user.posthog_version])

    return (
        <>
            {latestVersion ? (
                <span style={{ marginRight: 32 }}>
                    {latestVersion === user.posthog_version && (
                        <Button onClick={() => setChangelogOpen(true)} type="link" style={{ color: 'var(--green)' }}>
                            PostHog up-to-date
                        </Button>
                    )}
                    {latestVersion !== user.posthog_version && (
                        <Button type="link" onClick={() => setChangelogOpen(true)} style={{ color: 'var(--red)' }}>
                            New version available
                        </Button>
                    )}
                </span>
            ) : null}
            {changelogOpen && <ChangelogModal onDismiss={() => setChangelogOpen(false)} />}
        </>
    )
}
