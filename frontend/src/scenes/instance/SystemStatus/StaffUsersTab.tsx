import { useValues } from 'kea'
import { IconOpenInNew } from 'lib/components/icons'
import React from 'react'
import { staffUsersLogic } from './staffUsersLogic'

export function StaffUsersTab(): JSX.Element {
    const { staffUsers } = useValues(staffUsersLogic)

    return (
        <div>
            <div className="flex-center">
                <div style={{ flexGrow: 1 }}>
                    <h3 className="l3" style={{ marginTop: 16 }}>
                        Staff Users
                    </h3>
                    <div className="mb">
                        Users who have permissions to change instance-wide settings.{' '}
                        <a href="https://posthog.com/docs/self-host/configure/instance-settings" target="_blank">
                            Learn more <IconOpenInNew style={{ verticalAlign: 'middle' }} />
                        </a>
                        .
                    </div>
                </div>
            </div>
            {JSON.stringify(staffUsers)}
        </div>
    )
}
