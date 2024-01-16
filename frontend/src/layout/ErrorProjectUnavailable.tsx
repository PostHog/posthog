import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'

import { organizationLogic } from '../scenes/organizationLogic'

export function ErrorProjectUnavailable(): JSX.Element {
    const { projectCreationForbiddenReason } = useValues(organizationLogic)

    return (
        <div>
            <PageHeader />
            <p>
                {projectCreationForbiddenReason
                    ? "Switch to a project that you have access to. If you need a new project or access to an existing one that's private, ask a team member with administrator permissions."
                    : 'You can create a new project.'}
            </p>
        </div>
    )
}
