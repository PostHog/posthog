import React from 'react'
import { LatestVersion } from '~/layout/LatestVersion'
import { User } from '~/layout/User'

export function TopContent() {
    return (
        <div>
            <div
                className="right-align"
                style={{
                    display: 'flex',
                    flexDirection: 'row',
                    justifyContent: 'center',
                    alignItems: 'center',
                    fontSize: 13,
                }}
            >
                <LatestVersion />
                <User />
            </div>
        </div>
    )
}
