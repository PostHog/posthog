import './TopContent.scss'

import React from 'react'
import { LatestVersion } from '~/layout/LatestVersion'
import { User } from '~/layout/User'
import { Teams } from '~/layout/Teams'
import { WorkerStats } from '~/layout/WorkerStats'

export function TopContent() {
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
                <LatestVersion />
                <WorkerStats />
                <Teams />
                <User />
            </div>
        </div>
    )
}
