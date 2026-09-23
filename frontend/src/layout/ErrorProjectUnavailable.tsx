import { useValues } from 'kea'
import { useState } from 'react'

import { Link } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { CreateOrganizationModal } from 'scenes/organization/CreateOrganizationModal'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { organizationLogic } from '../scenes/organizationLogic'

export function ErrorProjectUnavailable(): JSX.Element {
    const { projectCreationForbiddenReason } = useValues(organizationLogic)
    const { user } = useValues(userLogic)
    const [options, setOptions] = useState<JSX.Element[]>([])
    // `organization.teams` lists only the projects this user can open, so a current project
    // that is unavailable is never in it. The list says nothing about whether access was
    // granted before, so the copy must not claim that access was removed.
    const hasVisibleProjects = (user?.organization?.teams?.length ?? 0) >= 1

    useOnMountEffect(() => {
        const options: JSX.Element[] = []
        if (!projectCreationForbiddenReason) {
            options.push(
                <Link key="create" to={urls.projectCreateFirst()}>
                    create a new project
                </Link>
            )
        }
        if (hasVisibleProjects) {
            options.push(<>switch to a project you have access to</>)
        }
        options.push(<>reach out to your administrator for access</>)
        setOptions(options)
    })

    const listOptions = (): JSX.Element => (
        <>
            {options.map((option: JSX.Element, index) => (
                <span key={index}>
                    {index > 0 && index < options.length - 1 ? ', ' : index > 0 ? ' or ' : ' '}
                    {option}
                </span>
            ))}
        </>
    )

    if (!user?.organization) {
        return <CreateOrganizationModal isVisible inline />
    }

    return (
        <div className="flex flex-col items-center max-w-2xl p-4 mx-auto my-24 text-center">
            {hasVisibleProjects ? (
                <>
                    <h1 className="text-3xl font-bold mt-4 mb-0">You don't have access to this project</h1>
                    <p className="text-sm mt-3 mb-0">You can{listOptions()}.</p>
                </>
            ) : (
                <>
                    <h1 className="text-3xl font-bold mt-4 mb-0">Welcome to {user?.organization?.name} on PostHog</h1>
                    <p className="text-sm mt-3 mb-0">
                        You do not have access to any projects in this organization. You can{listOptions()}.
                    </p>
                </>
            )}
        </div>
    )
}
