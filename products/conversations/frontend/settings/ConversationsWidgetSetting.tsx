import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { supportSettingsLogic } from './supportSettingsLogic'

export function ConversationsWidgetSetting(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { widgetEnabledLoading } = useValues(supportSettingsLogic)
    const { setWidgetEnabledLoading } = useActions(supportSettingsLogic)

    return (
        <LemonSwitch
            checked={!!currentTeam?.conversations_settings?.widget_enabled}
            onChange={(checked) => {
                setWidgetEnabledLoading(true)
                updateCurrentTeam({
                    conversations_settings: {
                        ...currentTeam?.conversations_settings,
                        widget_enabled: checked,
                    },
                })
            }}
            loading={widgetEnabledLoading}
            disabledReason={!currentTeam?.conversations_enabled ? 'Enable conversations API first' : undefined}
            bordered
            label="Enable in-app widget"
        />
    )
}
