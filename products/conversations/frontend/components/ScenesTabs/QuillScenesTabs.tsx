import { useActions, useValues } from 'kea'

import { Tabs, TabsList, TabsTrigger } from '@posthog/quill'

import type { SceneTabKey } from '../../types'
import { scenesTabsLogic } from './scenesTabsLogic'

export function QuillScenesTabs(): JSX.Element {
    const { tabs, activeTab } = useValues(scenesTabsLogic)
    const { setTab } = useActions(scenesTabsLogic)

    return (
        <Tabs value={activeTab} onValueChange={(key) => setTab(key as SceneTabKey)} className="border-b border-border">
            <TabsList variant="line" aria-label="Support sections" className="max-w-full justify-start overflow-x-auto">
                {tabs.map((tab) => (
                    <TabsTrigger key={tab.key} value={tab.key}>
                        {tab.label}
                    </TabsTrigger>
                ))}
            </TabsList>
        </Tabs>
    )
}
