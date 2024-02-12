import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'

import { groupsModel } from '~/models/groupsModel'

import { personsManagementSceneLogic } from './personsManagementSceneLogic'

export function PersonsManagementScene(): JSX.Element {
    const { tabs, activeTab, tabKey } = useValues(personsManagementSceneLogic)
    const { setTabKey } = useActions(personsManagementSceneLogic)
    const { showGroupsOptions } = useValues(groupsModel)

    const lemonTabs: LemonTab<string>[] = tabs.map((tab) => ({
        key: tab.key,
        label: <span data-attr={`persons-management-${tab.key}-tab`}>{tab.label}</span>,
        content: tab.content,
    }))

    return (
        <>
            <PageHeader
                caption={`A catalog of your product's end users, lists of users who have something in common to use in analytics or feature flags${
                    showGroupsOptions ? ' and groups' : ''
                }.`}
                buttons={activeTab?.buttons}
            />

            <LemonTabs activeKey={tabKey} onChange={(t) => setTabKey(t)} tabs={lemonTabs} />
        </>
    )
}

export const scene: SceneExport = {
    component: PersonsManagementScene,
    logic: personsManagementSceneLogic,
}
