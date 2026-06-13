import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { isMac } from 'lib/utils'
import { maxPreferencesLogic } from 'scenes/max/maxPreferencesLogic'

export function MaxSendShortcutSetting(): JSX.Element {
    const { sendWithCmdEnter } = useValues(maxPreferencesLogic)
    const { setSendWithCmdEnter } = useActions(maxPreferencesLogic)

    const sendKey = isMac() ? '⌘ + Enter' : 'Ctrl + Enter'

    return (
        <LemonSwitch
            onChange={setSendWithCmdEnter}
            checked={sendWithCmdEnter}
            label={`Send with ${sendKey}, and use Enter for a new line`}
            bordered
        />
    )
}
