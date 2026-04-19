import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { supportSettingsLogic } from './supportSettingsLogic'

export function ConversationsApiSetting(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { conversationsEnabledLoading } = useValues(supportSettingsLogic)
    const { setConversationsEnabledLoading } = useActions(supportSettingsLogic)

    return (
        <LemonSwitch
            checked={!!currentTeam?.conversations_enabled}
            onChange={(checked) => {
                setConversationsEnabledLoading(true)
                updateCurrentTeam({
                    conversations_enabled: checked,
                    conversations_settings: {
                        ...currentTeam?.conversations_settings,
                        widget_enabled: checked ? currentTeam?.conversations_settings?.widget_enabled : false,
                    },
                })
            }}
            loading={conversationsEnabledLoading}
            bordered
            label="Enable conversations API"
        />
    )
}
