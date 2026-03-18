import { useValues } from 'kea'

import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

import { personsManagementSceneLogic } from './personsManagementSceneLogic'

export interface PersonsManagementSceneTabsProps {
    tabKey: string
}

export function PersonsManagementSceneTabs({ tabKey }: PersonsManagementSceneTabsProps): JSX.Element {
    const { lemonTabs } = useValues(personsManagementSceneLogic)

    return <LemonTabs activeKey={tabKey} tabs={lemonTabs} sceneInset className="[&>ul]:mb-2" />
}
