import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { OsAppListing } from './OsAppListing'
import { OsAppStoreFront } from './OsAppStoreFront'
import { osAppStoreSceneLogic } from './osAppStoreSceneLogic'

export const scene: SceneExport = {
    component: OsAppStoreScene,
    logic: osAppStoreSceneLogic,
}

/** The App Store. It opens in an OS window like any other app, so it only exists with the OS shell on. */
export function OsAppStoreScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { selectedSlug } = useValues(osAppStoreSceneLogic)

    if (!featureFlags[FEATURE_FLAGS.OS_SHELL]) {
        return <NotFound object="page" />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.OsAppStore].name}
                description={sceneConfigurations[Scene.OsAppStore].description}
                resourceType={{ type: 'tools' }}
            />
            {selectedSlug ? <OsAppListing /> : <OsAppStoreFront />}
        </SceneContent>
    )
}
