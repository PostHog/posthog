import { AccessDenied } from 'lib/components/AccessDenied'
import { NotFound } from 'lib/components/NotFound'
import { getAppContext } from 'lib/utils/getAppContext'

export function ErrorProjectAccessDenied(): JSX.Element {
    // Staff keep the impersonation shortcut, which NotFound renders from the same app context.
    if (getAppContext()?.suggested_users_with_access) {
        return <NotFound object="project" />
    }

    return <AccessDenied reason="This link points to a project you're not a member of." />
}
