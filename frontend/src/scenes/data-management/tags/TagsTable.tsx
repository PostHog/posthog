import { useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { DefinitionsSceneTabs } from 'scenes/data-management/DefinitionsSceneTabs'

import { Error404 } from '~/layout/Error404'
import { ErrorAccessDenied } from '~/layout/ErrorAccessDenied'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { tagsLogic } from './tagsLogic'
import { TagsTableLemon } from './TagsTableLemon'
import { TagsTableQuill } from './TagsTableQuill'

export function TagsTable(): JSX.Element {
    const { canManageTags } = useValues(tagsLogic)
    const enabled = useFeatureFlag('TAG_MANAGEMENT')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!enabled) {
        return <Error404 />
    }
    if (!canManageTags) {
        return <ErrorAccessDenied />
    }

    return (
        <SceneContent className="ph-no-capture">
            <DefinitionsSceneTabs activeKey="tags" />
            <SceneTitleSection
                name="Tags"
                description="Manage tags across this project. Usage includes assignments to deleted items."
                descriptionAlwaysVisible={!todayRailNav}
                resourceType={{ type: 'tag' }}
            />
            {todayRailNav ? <TagsTableQuill /> : <TagsTableLemon />}
        </SceneContent>
    )
}
