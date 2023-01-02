import { SceneExport } from 'scenes/sceneTypes'
import { useActions, useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { Query } from '~/queries/Query/Query'
import { Persons } from 'scenes/persons/Persons'
import { PersonPageHeader } from 'scenes/persons/PersonPageHeader'
import { personsSceneLogic } from 'scenes/persons/personsSceneLogic'

export const scene: SceneExport = {
    component: PersonsScene,
}

export function PersonsScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const featureDataExploration = featureFlags[FEATURE_FLAGS.DATA_EXPLORATION_LIVE_EVENTS]
    const { query } = useValues(personsSceneLogic)
    const { setQuery } = useActions(personsSceneLogic)

    return (
        <>
            <PersonPageHeader />
            {featureDataExploration ? <Query query={query} setQuery={setQuery} /> : <Persons />}
        </>
    )
}
