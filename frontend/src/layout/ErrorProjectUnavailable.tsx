import React from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { useValues } from 'kea'
import { organizationLogic } from '../scenes/organizationLogic'

export function ErrorProjectUnavailable(): JSX.Element {
    const { isProjectCreationForbidden } = useValues(organizationLogic)

    return (
        <div>
            <PageHeader title="Project Unavailable" />
            <p>
                {isProjectCreationForbidden
                    ? "Switch to a project that you have access to. If you need a new project or access to an existing one that's private, ask a team member with administrator permissions."
                    : 'You can create a new project.'}
            </p>
        </div>
    )
}
