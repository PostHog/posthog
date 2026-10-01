import { useValues } from 'kea'

import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

import { DefinitionsSceneTabKey, definitionsSceneTabsLogic } from './definitionsSceneTabsLogic'

export function DefinitionsSceneTabs({ activeKey }: { activeKey: DefinitionsSceneTabKey }): JSX.Element {
    const { tabs } = useValues(definitionsSceneTabsLogic)

    return <LemonTabs activeKey={activeKey} tabs={tabs} sceneInset className="mb-3" />
}
