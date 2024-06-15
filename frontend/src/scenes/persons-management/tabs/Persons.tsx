import { useActions, useValues } from 'kea'
import { personsSceneLogic } from 'scenes/persons-management/tabs/personsSceneLogic'

import { Query } from '~/queries/Query/Query'

export function Persons(): JSX.Element {
    const { query } = useValues(personsSceneLogic)
    const { setQuery } = useActions(personsSceneLogic)

    return <Query query={query} setQuery={setQuery} context={{ alwaysRefresh: true }} />
}
