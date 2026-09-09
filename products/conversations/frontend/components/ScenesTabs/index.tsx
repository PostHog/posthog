import { useActions, useValues } from 'kea'

import { Tabs, TabsList, TabsTrigger } from 'lib/ui/quill'

import type { SceneTabKey } from '../../types'
import { type SceneTabConfig, scenesTabsLogic } from './scenesTabsLogic'

export function ScenesTabs(): JSX.Element {
    const { tabs, activeTab } = useValues(scenesTabsLogic)
    const { setTab } = useActions(scenesTabsLogic)

    return (
        <Tabs value={activeTab} onValueChange={(key) => setTab(key as SceneTabKey)}>
            <TabsList variant="line">
                {tabs.map((tab: SceneTabConfig) => (
                    <TabsTrigger key={tab.key} value={tab.key}>
                        {tab.label}
                    </TabsTrigger>
                ))}
            </TabsList>
        </Tabs>
    )
}
