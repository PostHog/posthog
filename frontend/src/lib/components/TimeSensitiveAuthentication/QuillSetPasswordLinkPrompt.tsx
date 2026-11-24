import { useActions, useValues } from 'kea'

import { Button, Text } from '@posthog/quill'

import { timeSensitiveAuthenticationLogic } from './timeSensitiveAuthenticationLogic'

export function QuillSetPasswordLinkPrompt(): JSX.Element {
    const { setPasswordLinkSentTo, setPasswordLinkSentToLoading } = useValues(timeSensitiveAuthenticationLogic)
    const { sendSetPasswordLink } = useActions(timeSensitiveAuthenticationLogic)

    return setPasswordLinkSentTo ? (
        <Text size="xs" variant="muted" render={<p className="m-0 text-center" />}>
            We sent a link to <b>{setPasswordLinkSentTo}</b>. Open it to set a password, then sign in with your new
            password.
        </Text>
    ) : (
        <Button
            type="button"
            className="self-center"
            loading={setPasswordLinkSentToLoading}
            onClick={sendSetPasswordLink}
            data-attr="reauth-set-password-link"
        >
            Can't use your passkey? Email me a link to set a password
        </Button>
    )
}
