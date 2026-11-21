import { useValues } from 'kea'

import { SceneTabs } from '~/layout/scenes/components/SceneTabs'

import { DefinitionsSceneTabKey, definitionsSceneTabsLogic } from './definitionsSceneTabsLogic'

export function DefinitionsSceneTabs({ activeKey }: { activeKey: DefinitionsSceneTabKey }): JSX.Element {
    const { tabs } = useValues(definitionsSceneTabsLogic)

    return <SceneTabs activeKey={activeKey} tabs={tabs} sceneInset className="mb-3" />
}
