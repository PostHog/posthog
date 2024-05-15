import { useActions, useValues } from 'kea'
import { eventsSceneLogic } from './eventsSceneLogic'

import { Query } from '~/queries/Query/Query'

export function EventsScene(): JSX.Element {
    const { query } = useValues(eventsSceneLogic)
    const { setQuery } = useActions(eventsSceneLogic)

    return <Query query={query} setQuery={setQuery} context={{ showOpenEditorButton: true }} />
}
