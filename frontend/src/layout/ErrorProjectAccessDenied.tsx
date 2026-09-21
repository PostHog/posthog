import { useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { AccessDenied } from 'lib/components/AccessDenied'
import { NotFound } from 'lib/components/NotFound'
import { getAppContext } from 'lib/utils/getAppContext'
import { PROJECT_ACCESS_DENIED_PARAM } from 'lib/utils/kea-router'

export function ErrorProjectAccessDenied(): JSX.Element {
    const { searchParams } = useValues(router)
    const appContext = getAppContext()
    const refusedProject = searchParams[PROJECT_ACCESS_DENIED_PARAM] || appContext?.project_access_denied
    const servedProjectName = appContext?.current_team?.name

    useEffect(() => {
        // A link can name the project by its API token, which is a credential, so the event carries
        // the id and nothing else.
        posthog.capture('project access denied', {
            refused_project_id: /^\d+$/.test(String(refusedProject ?? '')) ? Number(refusedProject) : null,
        })
    }, [refusedProject])

    // Staff keep the impersonation shortcut, which NotFound renders from the same app context.
    if (appContext?.suggested_users_with_access) {
        return <NotFound object="project" />
    }

    return (
        <AccessDenied
            reason={
                servedProjectName
                    ? `This link points to a project you're not a member of. You're in ${servedProjectName}.`
                    : "This link points to a project you're not a member of."
            }
        />
    )
}
