// DEPRECATED: this logic is now found in TopNavigation.tsx

import React, { useState } from 'react'
import { useValues } from 'kea'
import { Button } from 'antd'
import { ChangelogModal } from '~/layout/ChangelogModal'
import { useLatestVersion } from 'lib/hooks/useLatestVersion'
import { userLogic } from 'scenes/userLogic'
import { CheckOutlined, BulbOutlined } from '@ant-design/icons'

export function LatestVersion() {
    const { user } = useValues(userLogic)
    if (user.opt_out_capture) {
        return null
    }
    const [changelogOpen, setChangelogOpen] = useState(false)
    const latestVersion = useLatestVersion(user.posthog_version)
    const isApp = window.location.href.indexOf('app.posthog.com') > -1

    return (
        <>
            {latestVersion ? (
                <span>
                    {isApp ? (
                        <Button onClick={() => setChangelogOpen(true)} type="link" style={{ color: 'var(--success)' }}>
                            New features
                        </Button>
                    ) : (
                        <span>
                            {latestVersion === user.posthog_version && (
                                <Button
                                    onClick={() => setChangelogOpen(true)}
                                    type="link"
                                    style={{ color: 'var(--success)' }}
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
                                    style={{ color: 'var(--warning)' }}
                                >
                                    <span className="hide-when-small">
                                        <BulbOutlined /> New version available
                                    </span>
                                    <span className="show-when-small">
                                        <BulbOutlined /> Upgrade!
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
