import { useValues } from 'kea'

import { PageHeader } from 'lib/components/PageHeader'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

import { personsManagementSceneLogic } from './personsManagementSceneLogic'

export interface PersonsManagementSceneTabsProps {
    tabKey: string
    buttons?: JSX.Element
}

export function PersonsManagementSceneTabs({ tabKey, buttons }: PersonsManagementSceneTabsProps): JSX.Element {
    const { lemonTabs } = useValues(personsManagementSceneLogic)

    return (
        <>
            <PageHeader buttons={buttons} />

            <LemonTabs activeKey={tabKey} tabs={lemonTabs} sceneInset className="[&>ul]:mb-0" />
        </>
    )
}
