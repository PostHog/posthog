import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { SceneExport } from 'scenes/sceneTypes'

import { ChatTabs } from '../components/ChatTabs'
import { chatLogic } from './chatLogic'

export const scene: SceneExport = {
    component: ChatSettings,
    logic: chatLogic,
}

export function ChatSettings(): JSX.Element {
    // const { settings } = useValues(chatLogic) // Example: get settings from logic
    // const { updateSetting } = useActions(chatLogic) // Example: update setting in logic

    // Dummy state for now
    const isWidgetEnabled = true // Replace with actual logic value

    return (
        <>
            <ChatTabs activeTab="chat-settings" />
            <div className="p-4 space-y-6 max-w-2xl mx-auto">
                {/* Widget Settings Section */}
                <section>
                    <h2 className="text-xl font-semibold mb-3">Widget Settings</h2>
                    <div className="bg-white p-4 rounded border border-gray-200">
                        <LemonSwitch
                            label="Enable PostHog chat widget"
                            checked={isWidgetEnabled}
                            onChange={() => {}}
                            fullWidth
                        />
                        <p className="text-sm text-gray-500 mt-1">
                            Allow customers to chat with you directly from your website using the PostHog widget.
                        </p>
                    </div>
                </section>

                {/* Integrations Section */}
                <section>
                    <h2 className="text-xl font-semibold mb-3">Integrations</h2>
                    <div className="bg-white p-4 rounded border border-gray-200 space-y-4">
                        <div>
                            <h3 className="text-lg font-medium">Zendesk</h3>
                            <p className="text-sm text-gray-500">
                                Connect Zendesk to create tickets from chat conversations.
                            </p>
                            {/* Placeholder for Zendesk settings/button */}
                            <button className="mt-2 px-3 py-1.5 text-sm bg-blue-500 text-white rounded hover:bg-blue-600">
                                Configure Zendesk
                            </button>
                        </div>
                        <div>
                            <h3 className="text-lg font-medium">Jira</h3>
                            <p className="text-sm text-gray-500">
                                Connect Jira to create issues from chat conversations.
                            </p>
                            {/* Placeholder for Jira settings/button */}
                            <button className="mt-2 px-3 py-1.5 text-sm bg-gray-200 text-gray-700 rounded hover:bg-gray-300">
                                Configure Jira (Coming Soon)
                            </button>
                        </div>
                        {/* Add more integrations here */}
                    </div>
                </section>
            </div>
        </>
    )
}
