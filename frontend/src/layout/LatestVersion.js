import React, { useEffect, useState } from 'react'
import { useValues } from 'kea'
import api from './../lib/api'
import { Button } from 'antd'
import { ChangelogModal } from '~/layout/ChangelogModal'
import { userLogic } from 'scenes/userLogic'
import { CheckOutlined, WarningOutlined } from '@ant-design/icons'

export function LatestVersion() {
    const { user } = useValues(userLogic)
    if (user.opt_out_capture) return null
    const [latestVersion, setLatestVersion] = useState(null)
    const [changelogOpen, setChangelogOpen] = useState(false)
    const isApp = window.location.href.indexOf('app.posthog.com') > -1

    useEffect(() => {
        api.get('https://update.posthog.com/versions').then((versions) => {
            setLatestVersion(versions[0]['version'])
        })
    }, [user.posthog_version])

    return (
        <>
            {latestVersion ? (
                <span>
                    {isApp ? (
                        <Button onClick={() => setChangelogOpen(true)} type="link" style={{ color: 'var(--green)' }}>
                            New features
                        </Button>
                    ) : (
                        <span>
                            {latestVersion === user.posthog_version && (
                                <Button
                                    onClick={() => setChangelogOpen(true)}
                                    type="link"
                                    style={{ color: 'var(--green)' }}
                                >
                                    <span className="hide-when-small">
                                        <CheckOutlined /> PostHog up-to-date
                                    </span>
                                    <span className="show-when-small">
                                        <CheckOutlined /> {latestVersion}
                                    </span>
                                </Button>
                            )}
                            {latestVersion !== user.posthog_version && (
                                <Button
                                    type="link"
                                    onClick={() => setChangelogOpen(true)}
                                    style={{ color: 'var(--red)' }}
                                >
                                    <span className="hide-when-small">
                                        <WarningOutlined /> New version available
                                    </span>
                                    <span className="show-when-small">
                                        <WarningOutlined /> Upgrade!
                                    </span>
                                </Button>
                            )}
                        </span>
                    )}
                </span>
            ) : null}
            {changelogOpen && <ChangelogModal onDismiss={() => setChangelogOpen(false)} />}
        </>
    )
}
