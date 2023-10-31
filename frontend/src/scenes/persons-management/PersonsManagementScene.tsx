import { useActions, useValues } from 'kea'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'

import { groupsModel } from '~/models/groupsModel'
import { PageHeader } from 'lib/components/PageHeader'
import { personsManagementSceneLogic } from './personsManagementSceneLogic'

export function PersonsManagementScene(): JSX.Element {
    const { tabs, tab } = useValues(personsManagementSceneLogic)
    const { setTab } = useActions(personsManagementSceneLogic)
    const { showGroupsOptions } = useValues(groupsModel)

    const lemonTabs: LemonTab<string>[] = Object.entries(tabs).map(([key, tab]) => ({
        key: key,
        label: <span data-attr={`persons-management-${key}-tab`}>{tab.label}</span>,
        content: tab.content,
    }))

    return (
        <>
            <PageHeader
                title={`Persons${showGroupsOptions ? ', cohorts & groups' : '& cohorts'}`}
                caption={`A catalog of your product's end users, lists of users who have something in common to use in analytics or feature flags${
                    showGroupsOptions ? ' and groups' : ''
                }.`}
                buttons={tabs[tab].buttons}
            />

            <LemonTabs activeKey={tab} onChange={(t) => setTab(t)} tabs={lemonTabs} />
        </>
    )
}

export const scene: SceneExport = {
    component: PersonsManagementScene,
    logic: personsManagementSceneLogic,
}
