import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { NotFound } from 'lib/components/NotFound'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { getAppContext } from 'lib/utils/getAppContext'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { usersRetrieve } from '~/generated/core/api'

export function ErrorProjectAccessDenied(): JSX.Element {
    const { user } = useValues(userLogic)
    const { logout } = useActions(userLogic)
    const { isCurrentProjectAccessDenied } = useValues(teamLogic)
    const [signedInEmail, setSignedInEmail] = useState(user?.email)
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
        // Another tab can sign in as a different account, which the server then refuses here. Read the
        // email the server sees without reloading `userLogic`, which drops the user and blanks the app
        // when the request fails.
        if (isCurrentProjectAccessDenied) {
            usersRetrieve('@me')
                .then((signedInUser) => setSignedInEmail(signedInUser.email))
                .catch(() => {})
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
                    {signedInEmail ? (
                        <>
                            {' '}
                            You're signed in as <strong>{signedInEmail}</strong>.
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
