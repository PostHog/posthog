import { LemonTabs } from '@posthog/lemon-ui'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

const tabs = [
    {
        label: 'Chats',
        key: 'chat-list',
        url: urls.chatList(),
    },
    {
        label: 'Settings',
        key: 'chat-settings',
        url: urls.chatSettings(),
    },
]

export function ChatTabs({ activeTab }: { activeTab: string }): JSX.Element {
    return (
        <LemonTabs
            activeKey={activeTab}
            onChange={(t) => router.actions.push(tabs.find((tab) => tab.key === t)?.url ?? '')}
            tabs={tabs.map((tab) => {
                return {
                    label: tab.label,
                    key: tab.key,
                }
            })}
        />
    )
}
