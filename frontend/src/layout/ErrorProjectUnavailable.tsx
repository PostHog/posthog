import React from 'react'
import { PageHeader } from 'lib/components/PageHeader'

export function ErrorProjectUnavailable(): JSX.Element {
    return (
        <div>
            <PageHeader title="Project Unavailable" />
            <p>
                It seems you don't have access to this project.
                <br />
                Switch to one that you do have access to, or ask a team member with administrator permissions for
                access.
            </p>
        </div>
    )
}
