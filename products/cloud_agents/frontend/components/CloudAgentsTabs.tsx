import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { urls } from 'scenes/urls'

export type CloudAgentsTabKey = 'runs' | 'presets' | 'usage' | 'settings'

/** Each tab is a scene with its own URL, so the bar only links and holds no content. */
export function CloudAgentsTabs({ activeTab }: { activeTab: CloudAgentsTabKey }): JSX.Element {
    const tabs: LemonTab<CloudAgentsTabKey>[] = [
        { key: 'runs', label: 'Runs', link: urls.cloudAgents() },
        { key: 'presets', label: 'Presets', link: urls.cloudAgentPresets() },
        { key: 'usage', label: 'Usage', link: urls.cloudAgentsUsage() },
        { key: 'settings', label: 'Settings', link: urls.cloudAgentsSettings() },
    ]
    return <LemonTabs activeKey={activeTab} tabs={tabs} data-attr="cloud-agents-tabs" sceneInset />
}
