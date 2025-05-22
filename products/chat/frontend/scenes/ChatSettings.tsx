import { useActions, useValues } from 'kea'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { SceneExport } from 'scenes/sceneTypes'
import { SupportedPlatforms } from 'scenes/settings/environment/SessionRecordingSettings'
import { teamLogic } from 'scenes/teamLogic'

import { ChatTabs } from '../components/ChatTabs'
import { chatLogic } from './chatLogic'

export const scene: SceneExport = {
    component: ChatSettings,
    logic: chatLogic,
}

export function ChatSettings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    /**
     * Handle the opt in change
     * @param checked
     */
    const handleOptInChange = (checked: boolean): void => {
        updateCurrentTeam({
            session_recording_opt_in: checked,
        })
    }

    return (
        <>
            <ChatTabs activeTab="chat-settings" />
            <div className="flex flex-col gap-4">
                <div>
                    <h3>PostHog chat widget</h3>
                    <p>The PostHog chat widget is a widget that allows you to chat with your users.</p>
                    <SupportedPlatforms
                        android={false}
                        ios={false}
                        flutter={false}
                        web={{ version: '1.5.0' }}
                        reactNative={false}
                    />

                    <LemonSwitch
                        data-attr="opt-in-chat-feature-switch"
                        onChange={(checked) => {
                            handleOptInChange(checked)
                        }}
                        label="Enable PostHog chat widget"
                        bordered
                        checked={!!currentTeam?.session_recording_opt_in}
                    />
                </div>
            </div>
        </>
    )
}
