import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

import { groupsModel } from '~/models/groupsModel'

import { personsManagementSceneLogic } from './personsManagementSceneLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneTitleSection } from '~/layout/scenes/SceneContent'
const RESOURCE_TYPE = 'cohort'

export interface PersonsManagementSceneTabsProps {
    tabKey: string
    buttons?: JSX.Element
}
export function PersonsManagementSceneTabs({ tabKey, buttons }: PersonsManagementSceneTabsProps): JSX.Element {
    const { lemonTabs } = useValues(personsManagementSceneLogic)
    const { showGroupsOptions } = useValues(groupsModel)
    const { featureFlags } = useValues(featureFlagLogic)
    const newSceneLayout = featureFlags[FEATURE_FLAGS.NEW_SCENE_LAYOUT]

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

            {newSceneLayout && (
                <SceneTitleSection
                    name="Cohorts"
                    description={
                        showGroupsOptions
                            ? 'A catalog of identified persons, groups, and your created cohorts.'
                            : 'A catalog of identified persons and your created cohorts.'
                    }
                    resourceType={{
                        type: RESOURCE_TYPE,
                        typePlural: 'cohorts',
                    }}
                />
            )}

            <LemonTabs activeKey={tabKey} tabs={lemonTabs} />
        </>
    )
}
