import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { platformCommandControlKey } from 'lib/utils'
import { userLogic } from 'scenes/userLogic'

export function AIChatSendKeySetting(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

    return (
        <LemonSwitch
            onChange={(checked) => {
                updateUser({ ai_chat_send_on_cmd_enter: checked })
            }}
            checked={user?.ai_chat_send_on_cmd_enter ?? false}
            loading={userLoading}
            label={`Require ${platformCommandControlKey('Enter')} to send (Enter adds a new line)`}
            bordered
        />
    )
}
