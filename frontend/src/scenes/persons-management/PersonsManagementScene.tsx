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
        tooltipDocLink: tab.tooltipDocLink,
    }))

    return (
        <>
            <PageHeader
                caption={
                    showGroupsOptions
                        ? 'A catalog of identified persons, groups, and your created cohorts.'
                        : 'A catalog of identified persons and your created cohorts.'
                }
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
