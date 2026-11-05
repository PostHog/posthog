import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { NotFound } from 'lib/components/NotFound'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { getAppContext } from 'lib/utils/getAppContext'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

export function ErrorProjectAccessDenied(): JSX.Element {
    const { user } = useValues(userLogic)
    const { loadUser, logout } = useActions(userLogic)
    const { isCurrentProjectAccessDenied } = useValues(teamLogic)
    // Staff keep the impersonation shortcut, which NotFound renders from the same app context.
    const showsImpersonationShortcut = !!getAppContext()?.suggested_users_with_access

    useOnMountEffect(() => {
        if (showsImpersonationShortcut) {
            return
        }
        // pinned: analytics event name and property values, renaming breaks dashboards
        posthog.capture('project access denied shown', {
            cause: isCurrentProjectAccessDenied ? 'access_lost' : 'refused_link',
        })
        // Another tab can sign in as a different account, which the server then refuses here. Reload
        // the user so the email shown is the account the server sees, not the one this page loaded with.
        if (isCurrentProjectAccessDenied) {
            loadUser()
        }
    })

    if (showsImpersonationShortcut) {
        return <NotFound object="project" />
    }

    return (
        <AccessDenied
            reason={
                <>
                    <span>
                        {isCurrentProjectAccessDenied
                            ? "You don't have access to this project."
                            : "This link points to a project you're not a member of."}
                    </span>
                    {user?.email ? (
                        <>
                            {' '}
                            You're signed in as <strong>{user.email}</strong>.
                        </>
                    ) : null}
                </>
            }
        >
            <LemonButton
                type="secondary"
                className="mt-4"
                data-attr="project-access-denied-sign-in-different-account"
                onClick={() => {
                    // pinned: analytics event name, renaming breaks dashboards
                    posthog.capture('project access denied sign in with different account clicked')
                    logout(true)
                }}
            >
                Sign in with a different account
            </LemonButton>
        </AccessDenied>
    )
}
