import { useValues } from 'kea'

import { SceneTabs } from '~/layout/scenes/components/SceneTabs'
import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { DefinitionsSceneTabKey, definitionsSceneTabsLogic } from './definitionsSceneTabsLogic'

/** The tabs of the definitions pages. The Data pane links each page, so there it shows no tabs. */
export function DefinitionsSceneTabs({ activeKey }: { activeKey: DefinitionsSceneTabKey }): JSX.Element | null {
    const { tabs } = useValues(definitionsSceneTabsLogic)
    const { dataPaneLinksTabs } = useValues(todayShellLogic)

    if (dataPaneLinksTabs) {
        return null
    }

    return <SceneTabs activeKey={activeKey} tabs={tabs} sceneInset className="mb-3" />
}
