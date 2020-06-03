import './TopContent.scss'

import React from 'react'
import { LatestVersion } from '~/layout/LatestVersion'
import { User } from '~/layout/User'
import { WorkerStats } from '~/layout/WorkerStats'
import { OnboardingWidget } from '~/layout/onboarding'
import { userLogic } from 'scenes/userLogic'
import { useValues } from 'kea'

export function TopContent() {
    const { user } = useValues(userLogic)
    return (
        <div>
            <div
                className="layout-top-content right-align"
                style={{
                    display: 'flex',
                    flexDirection: 'row',
                    justifyContent: 'center',
                    alignItems: 'center',
                    fontSize: 13,
                }}
            >
                {user.has_events && user.onboarding.active && <OnboardingWidget />}
                <LatestVersion />
                <WorkerStats />
                <User />
            </div>
        </div>
    )
}
