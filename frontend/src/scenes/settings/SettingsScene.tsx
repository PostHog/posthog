import { useValues } from 'kea'
import { router } from 'kea-router'

import { useAnchor } from 'lib/hooks/useAnchor'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { Settings } from './Settings'
import { settingsLogic } from './settingsLogic'
import { settingsSceneLogic } from './settingsSceneLogic'
import { SettingLevelNames } from './types'

export const scene: SceneExport = {
    component: SettingsScene,
    logic: settingsSceneLogic,
}

export function SettingsScene(): JSX.Element {
    const { location } = useValues(router)
    const { selectedLevel, selectedSectionId, selectedSection, sections } = useValues(
        settingsLogic({ logicKey: 'settingsScene' })
    )
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    useAnchor(location.hash)

    const sectionName = selectedSectionId
        ? sections.find((x) => x.id === selectedSectionId)?.title
        : capitalizeFirstLetter(selectedLevel)

    const title = sectionName ? `Settings - ${sectionName}` : 'Settings'

    return (
        <SceneContent>
            {todayRailNav && (
                <SceneTitleSection
                    name={typeof sectionName === 'string' && sectionName ? sectionName : 'Settings'}
                    resourceType={{ type: 'settings' }}
                    // A level-only page already names the level, so only a section gets the level crumb.
                    scope={selectedSection ? SettingLevelNames[selectedSection.level] : undefined}
                />
            )}
            <Settings
                logicKey="settingsScene"
                handleLocally
                hideSections={todayRailNav}
                headerSlot={todayRailNav ? null : <h1 className="text-2xl font-semibold m-0 mb-4">{title}</h1>}
            />
        </SceneContent>
    )
}
