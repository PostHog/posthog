import { useValues } from 'kea'

import { AccessDenied } from 'lib/components/AccessDenied'
import { NotFound } from 'lib/components/NotFound'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { getAppContext } from 'lib/utils/getAppContext'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

export function ErrorProjectAccessDenied(): JSX.Element {
    const { isAdminOrOwner } = useValues(organizationLogic)

    // Staff keep the impersonation shortcut, which NotFound renders from the same app context.
    if (getAppContext()?.suggested_users_with_access) {
        return <NotFound object="project" />
    }

    return (
        <AccessDenied
            reason="This link points to a project you're not a member of."
            suggestAdministrators={!isAdminOrOwner}
            actions={
                <LemonButton type="primary" to={urls.projectHomepage()} data-attr="project-access-denied-open-own">
                    Open your project
                </LemonButton>
            }
        />
    )
}
