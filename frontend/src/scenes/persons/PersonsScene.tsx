import { SceneExport } from 'scenes/sceneTypes'
import { useActions, useValues } from 'kea'
import { Query } from '~/queries/Query/Query'
import { PersonPageHeader } from 'scenes/persons/PersonPageHeader'
import { personsSceneLogic } from 'scenes/persons/personsSceneLogic'

export const scene: SceneExport = {
    component: PersonsScene,
}

export function PersonsScene(): JSX.Element {
    const { query } = useValues(personsSceneLogic)
    const { setQuery } = useActions(personsSceneLogic)

    return (
        <>
            <PersonPageHeader activeGroupTypeIndex={-1} />
            <Query query={query} setQuery={setQuery} />
        </>
    )
}
