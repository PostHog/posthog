import React, { useEffect, useState } from 'react'
import { useValues } from 'kea'
import api from './../lib/api'
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
                        <a
                            href="#"
                            onClick={() => setChangelogOpen(true)}
                            className="text-success"
                            style={{ marginRight: 16 }}
                        >
                            PostHog up-to-date
                        </a>
                    )}
                    {latestVersion !== user.posthog_version && (
                        <a
                            href="#"
                            onClick={() => setChangelogOpen(true)}
                            className="text-danger"
                            style={{ marginRight: 16 }}
                        >
                            New version available
                        </a>
                    )}
                </span>
            ) : null}
            {changelogOpen && <ChangelogModal onDismiss={() => setChangelogOpen(false)} />}
        </>
    )
}
