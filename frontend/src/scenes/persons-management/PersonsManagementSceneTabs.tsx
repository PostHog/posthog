import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

import { groupsModel } from '~/models/groupsModel'

import { personsManagementSceneLogic } from './personsManagementSceneLogic'

export interface PersonsManagementSceneTabsProps {
    tabKey: string
    buttons?: JSX.Element
}
export function PersonsManagementSceneTabs({ tabKey, buttons }: PersonsManagementSceneTabsProps): JSX.Element {
    const { lemonTabs } = useValues(personsManagementSceneLogic)
    const { showGroupsOptions } = useValues(groupsModel)

    return (
        <>
            <PageHeader
                caption={
                    showGroupsOptions
                        ? 'A catalog of identified persons, groups, and your created cohorts.'
                        : 'A catalog of identified persons and your created cohorts.'
                }
                buttons={buttons}
            />

            <LemonTabs activeKey={tabKey} tabs={lemonTabs} />
        </>
    )
}
