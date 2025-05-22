import { useActions, useValues } from 'kea'
import { getSeriesColorPalette } from 'lib/colors'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonColorPicker } from 'lib/lemon-ui/LemonColor'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { useState } from 'react'
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

    const [startMessage, setStartMessage] = useState(currentTeam?.chat_config?.start_message)
    /**
     * Handle the opt in change
     * @param checked
     */
    const handleOptInChange = (checked: boolean): void => {
        updateCurrentTeam({
            chat_opt_in: checked,
        })
    }

    const handleStartMessageChange = (): void => {
        updateCurrentTeam({
            chat_config: {
                ...currentTeam?.chat_config,
                start_message: startMessage,
            },
        })
    }

    return (
        <>
            <ChatTabs activeTab="chat-settings" />
            <div className="flex flex-col gap-4">
                <div>
                    <h2>PostHog chat widget</h2>
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
                        checked={!!currentTeam?.chat_opt_in}
                    />
                </div>
                <div className="mt-4">
                    <h3>Chat widget configuration</h3>
                    <div className="my-4">
                        <h4>Brand color</h4>
                        <p>The color of the chat widget.</p>
                        <LemonColorPicker
                            selectedColor={currentTeam?.chat_config?.brand_color}
                            onSelectColor={(color) => {
                                updateCurrentTeam({
                                    chat_config: {
                                        ...currentTeam?.chat_config,
                                        brand_color: color,
                                    },
                                })
                            }}
                            colors={getSeriesColorPalette().slice(0, 10)}
                            showCustomColor
                            hideDropdown
                            preventPopoverClose
                        />
                    </div>
                    <div className="my-4">
                        <h4>Start message</h4>
                        <p>The message that will be shown when the chat widget is opened.</p>
                        <div className="flex gap-4">
                            <LemonInput
                                value={startMessage}
                                onChange={(e) => {
                                    setStartMessage(e)
                                }}
                            />
                            <LemonButton onClick={handleStartMessageChange} type="primary">
                                Save
                            </LemonButton>
                        </div>
                    </div>
                </div>
            </div>
        </>
    )
}
