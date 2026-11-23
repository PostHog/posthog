import { useActions, useValues } from 'kea'

import { IconLock } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { oauthAuthorizeLogic, oauthReauthenticationPrompt } from './oauthAuthorizeLogic'

/** Shown instead of an immediate redirect when the app skips consent but the sign-in is too old to issue a code. */
export function OAuthAuthorizeReauthentication(): JSX.Element {
    const { appName, user, isCanceling, isContinuingAfterReauthentication } = useValues(oauthAuthorizeLogic)
    const { reauthenticate, cancel } = useActions(oauthAuthorizeLogic)
    const prompt = oauthReauthenticationPrompt(appName)

    return (
        <div className="AuthScene__card flex flex-col items-center gap-4 p-8 text-center">
            <IconLock className="text-muted-alt text-4xl" />
            <div className="text-xl font-semibold">{prompt.title}</div>
            <div className="text-sm text-muted">{prompt.description}</div>
            {user && (
                <div className="text-sm text-muted break-words">
                    <span>Signed in as </span>
                    <span className="font-semibold text-primary">{user.email}</span>
                </div>
            )}
            {isContinuingAfterReauthentication ? (
                <div className="flex items-center gap-2 text-sm text-muted">
                    <Spinner />
                    <span>Continuing to {appName}</span>
                </div>
            ) : (
                <div className="flex flex-wrap justify-center gap-2">
                    <LemonButton
                        type="secondary"
                        onClick={cancel}
                        loading={isCanceling}
                        data-attr="oauth-authorize-reauthentication-cancel"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={reauthenticate} data-attr="oauth-authorize-reauthenticate">
                        Sign in again
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
