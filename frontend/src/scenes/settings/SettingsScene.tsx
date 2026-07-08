import { useValues } from 'kea'
import { router } from 'kea-router'

import { useAnchor } from 'lib/hooks/useAnchor'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { Settings } from './Settings'
import { settingsLogic } from './settingsLogic'
import { settingsSceneLogic } from './settingsSceneLogic'

export const scene: SceneExport = {
    component: SettingsScene,
    logic: settingsSceneLogic,
}

export function SettingsScene(): JSX.Element {
    const { location } = useValues(router)
    const { selectedLevel, selectedSectionId, sections } = useValues(settingsLogic({ logicKey: 'settingsScene' }))
    useAnchor(location.hash)

    const sectionName = selectedSectionId
        ? sections.find((x) => x.id === selectedSectionId)?.title
        : capitalizeFirstLetter(selectedLevel)

    const title = sectionName ? `Settings - ${sectionName}` : 'Settings'

    return (
        <SceneContent>
            <Settings
                logicKey="settingsScene"
                handleLocally
                headerSlot={<h1 className="text-2xl font-semibold m-0 mb-4">{title}</h1>}
            />
        </SceneContent>
    )
}
