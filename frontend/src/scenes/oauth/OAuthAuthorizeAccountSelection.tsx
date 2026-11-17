import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'

import { oauthAuthorizeLogic } from './oauthAuthorizeLogic'

export function OAuthAuthorizeAccountSelection(): JSX.Element {
    const { appName, user, accountChoice } = useValues(oauthAuthorizeLogic)
    const { chooseAccount } = useActions(oauthAuthorizeLogic)

    return (
        <>
            <AuthCardTitle
                title="Choose an account"
                sub={`Pick the PostHog account to use with ${appName}.`}
                className="shrink-0 mb-3"
            />
            <div className="AuthScene__card flex flex-col gap-4 p-4 sm:p-6">
                {user && (
                    <div className="flex items-center gap-3 min-w-0">
                        <ProfilePicture user={user} size="lg" className="shrink-0" />
                        <div className="flex flex-col min-w-0">
                            <span className="font-semibold truncate">{user.email}</span>
                            <span className="text-sm text-muted truncate">{window.location.host}</span>
                        </div>
                    </div>
                )}
                <div className="flex flex-col gap-2">
                    <LemonButton
                        type="primary"
                        size="large"
                        fullWidth
                        center
                        data-attr="oauth-account-selection-continue"
                        loading={accountChoice === 'current_account'}
                        disabledReason={accountChoice === 'different_account' ? 'Signing out' : undefined}
                        onClick={() => chooseAccount('current_account')}
                    >
                        Continue with this account
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        size="large"
                        fullWidth
                        center
                        data-attr="oauth-account-selection-different-account"
                        loading={accountChoice === 'different_account'}
                        disabledReason={accountChoice === 'current_account' ? 'Continuing' : undefined}
                        onClick={() => chooseAccount('different_account')}
                    >
                        Use a different account
                    </LemonButton>
                    <p className="m-0 text-xs text-muted text-center text-pretty">
                        Using a different account signs you out of PostHog in this browser.
                    </p>
                </div>
            </div>
        </>
    )
}
