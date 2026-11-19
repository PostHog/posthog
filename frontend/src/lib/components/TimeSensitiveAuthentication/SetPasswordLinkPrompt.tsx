import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { timeSensitiveAuthenticationLogic } from './timeSensitiveAuthenticationLogic'

export function SetPasswordLinkPrompt(): JSX.Element {
    const { setPasswordLinkSentTo, setPasswordLinkSentToLoading } = useValues(timeSensitiveAuthenticationLogic)
    const { sendSetPasswordLink } = useActions(timeSensitiveAuthenticationLogic)

    return (
        <div className="mt-4 flex justify-center text-center text-secondary">
            {setPasswordLinkSentTo ? (
                <p className="m-0">
                    We sent a link to <b>{setPasswordLinkSentTo}</b>. Open it to set a password, then sign in with your
                    new password.
                </p>
            ) : (
                <LemonButton
                    type="tertiary"
                    size="small"
                    htmlType="button"
                    loading={setPasswordLinkSentToLoading}
                    onClick={sendSetPasswordLink}
                    data-attr="reauth-set-password-link"
                >
                    Can't use your passkey? Email me a link to set a password
                </LemonButton>
            )}
        </div>
    )
}
