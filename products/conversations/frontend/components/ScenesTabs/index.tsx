import { useActions, useValues } from 'kea'

import { LemonTabs } from '@posthog/lemon-ui'

import type { SceneTabKey } from '../../types'
import { type SceneTabConfig, scenesTabsLogic } from './scenesTabsLogic'

export function ScenesTabs(): JSX.Element {
    const { tabs, activeTab } = useValues(scenesTabsLogic)
    const { setTab } = useActions(scenesTabsLogic)

    return (
        <LemonTabs
            activeKey={activeTab}
            tabs={tabs.map((tab: SceneTabConfig) => ({
                key: tab.key,
                label: tab.label,
            }))}
            onChange={(key) => setTab(key as SceneTabKey)}
            sceneInset
        />
    )
}
