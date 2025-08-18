import { useValues } from 'kea'

import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { groupsModel } from '~/models/groupsModel'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { personsManagementSceneLogic } from './personsManagementSceneLogic'

export interface PersonsManagementSceneTabsProps {
    tabKey: string
    buttons?: JSX.Element
}
export function PersonsManagementSceneTabs({ tabKey, buttons }: PersonsManagementSceneTabsProps): JSX.Element {
    const { lemonTabs } = useValues(personsManagementSceneLogic)
    const { showGroupsOptions } = useValues(groupsModel)
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    return (
        <>
            <PageHeader
                caption={
                    !newSceneLayout
                        ? showGroupsOptions
                            ? 'A catalog of identified persons, groups, and your created cohorts.'
                            : 'A catalog of identified persons and your created cohorts.'
                        : null
                }
                buttons={buttons}
            />

            <LemonTabs activeKey={tabKey} tabs={lemonTabs} sceneInset={newSceneLayout} />
        </>
    )
}
